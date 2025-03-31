import threading
from functools import lru_cache
from typing import Callable
from uuid import UUID

import requests
import tenacity

from openhands.core.config import AppConfig
from openhands.core.exceptions import (
    AgentRuntimeDisconnectedError,
    AgentRuntimeNotFoundError,
)
from openhands.core.logger import DEBUG, DEBUG_RUNTIME
from openhands.core.logger import openhands_logger as logger
from openhands.events import EventStream
from openhands.runtime.builder import DockerRuntimeBuilder
from openhands.runtime.impl.action_execution.action_execution_client import (
    ActionExecutionClient,
)
from openhands.runtime.plugins import PluginRequirement
from openhands.runtime.utils import find_available_tcp_port
from openhands.runtime.utils.command import get_action_execution_server_startup_command
from openhands.runtime.utils.runtime_build import build_runtime_image
from openhands.utils.async_utils import call_sync_from_async
from openhands.utils.shutdown_listener import add_shutdown_listener
from openhands.utils.tenacity_stop import stop_if_should_exit

# Constants
POD_NAME_PREFIX = 'openhands-runtime-'

EXECUTION_SERVER_PORT_RANGE = (30000, 39999)
VSCODE_PORT_RANGE = (40000, 49999)
APP_PORT_RANGE_1 = (50000, 54999)
APP_PORT_RANGE_2 = (55000, 59999)


class KubernetesLogStreamer:
    """Stream logs from a Kubernetes pod."""

    def __init__(self, k8s_client, namespace, pod_name, log_callback):
        self.k8s_client = k8s_client
        self.namespace = namespace
        self.pod_name = pod_name
        self.log_callback = log_callback
        self.running = True
        self.thread = threading.Thread(target=self._stream_logs)
        self.thread.daemon = True
        self.thread.start()

    def _stream_logs(self):
        """Stream logs from the pod in a separate thread."""
        try:
            logs = self.k8s_client.CoreV1Api().read_namespaced_pod_log(
                name=self.pod_name,
                namespace=self.namespace,
                follow=True,
                _preload_content=False,
            )

            for line in logs:
                if not self.running:
                    break
                if line:
                    self.log_callback('debug', line.decode('utf-8').strip())
        except Exception as e:
            self.log_callback('error', f'Log streaming error: {e}')

    def close(self):
        """Stop the log streaming thread."""
        self.running = False


def delete_all_k8s_resources(namespace, name_prefix):
    """Delete all Kubernetes resources with the given prefix in the namespace."""
    try:
        from kubernetes import client, config

        # Try loading from kube config file
        try:
            config.load_kube_config()
        except Exception:
            # Fallback to in-cluster config (if running inside K8s)
            config.load_incluster_config()

        k8s_client = client

        # Delete pods with the prefix
        pods = k8s_client.CoreV1Api().list_namespaced_pod(
            namespace=namespace, label_selector='app=openhands-runtime'
        )

        for pod in pods.items:
            if pod.metadata.name.startswith(name_prefix):
                try:
                    k8s_client.CoreV1Api().delete_namespaced_pod(
                        name=pod.metadata.name, namespace=namespace
                    )
                    logger.debug(f'Deleted pod: {pod.metadata.name}')
                except Exception as e:
                    logger.error(f'Failed to delete pod {pod.metadata.name}: {e}')

        # Delete services with the prefix
        services = k8s_client.CoreV1Api().list_namespaced_service(namespace=namespace)

        for service in services.items:
            if service.metadata.name.startswith(f'{name_prefix}'):
                try:
                    k8s_client.CoreV1Api().delete_namespaced_service(
                        name=service.metadata.name, namespace=namespace
                    )
                    logger.debug(f'Deleted service: {service.metadata.name}')
                except Exception as e:
                    logger.error(
                        f'Failed to delete service {service.metadata.name}: {e}'
                    )

        # Note: We don't delete PVCs automatically to preserve data

    except Exception as e:
        logger.error(f'Failed to delete kubernetes resources: {e}')


class KubernetesRuntime(ActionExecutionClient):
    """This runtime will run inside a Kubernetes cluster.

    Args:
        config (AppConfig): The application configuration.
        event_stream (EventStream): The event stream to subscribe to.
        sid (str, optional): The session ID. Defaults to 'default'.
        plugins (list[PluginRequirement] | None, optional): List of plugin requirements. Defaults to None.
        env_vars (dict[str, str] | None, optional): Environment variables to set. Defaults to None.
        namespace (str, optional): Kubernetes namespace. Defaults to 'openhands-runtime'.
    """

    _shutdown_listener_id: UUID | None = None

    def __init__(
        self,
        config: AppConfig,
        event_stream: EventStream,
        sid: str = 'default',
        plugins: list[PluginRequirement] | None = None,
        env_vars: dict[str, str] | None = None,
        status_callback: Callable | None = None,
        attach_to_existing: bool = False,
        headless_mode: bool = True,
        namespace: str = 'openhands-runtime',
    ):
        if not KubernetesRuntime._shutdown_listener_id:
            KubernetesRuntime._shutdown_listener_id = add_shutdown_listener(
                lambda: delete_all_k8s_resources(namespace, POD_NAME_PREFIX)
            )

        self.config = config
        self._runtime_initialized: bool = False
        self.status_callback = status_callback
        self.namespace = namespace

        self._host_port = -1
        self._container_port = -1
        self._vscode_port = -1
        self._app_ports: list[int] = []

        self.k8s_client = self._init_k8s_client()
        self.api_url = None

        self.base_container_image = self.config.sandbox.base_container_image
        self.runtime_container_image = self.config.sandbox.runtime_container_image
        self.pod_name = POD_NAME_PREFIX + sid
        self.pod = None

        # elf.runtime_builder = DockerRuntimeBuilder(None)  # We'll still use Docker to build images

        # Buffer for container logs
        self.log_streamer: KubernetesLogStreamer | None = None

        super().__init__(
            config,
            event_stream,
            sid,
            plugins,
            env_vars,
            status_callback,
            attach_to_existing,
            headless_mode,
        )

        # Log runtime_extra_deps after base class initialization so self.sid is available
        if self.config.sandbox.runtime_extra_deps:
            self.log(
                'debug',
                f'Installing extra user-provided dependencies in the runtime image: {self.config.sandbox.runtime_extra_deps}',
            )

    def _get_action_execution_server_host(self):
        return self.api_url

    @staticmethod
    @lru_cache(maxsize=1)
    def _init_k8s_client():
        """Initialize Kubernetes client configuration."""
        try:
            from kubernetes import client, config

            # Try loading from kube config file
            try:
                config.load_kube_config()
            except Exception:
                # Fallback to in-cluster config (if running inside K8s)
                config.load_incluster_config()

            return client
        except ImportError:
            logger.error(
                "Kubernetes client not installed. Install with 'pip install kubernetes'"
            )
            raise
        except Exception as ex:
            logger.error(
                'Failed to initialize Kubernetes client. Please ensure you have proper K8s configuration.'
            )
            raise ex

    async def connect(self):
        self.send_status_message('STATUS$STARTING_RUNTIME')
        try:
            await call_sync_from_async(self._attach_to_pod)
        except Exception as e:
            if self.attach_to_existing:
                self.log(
                    'error',
                    f'Pod {self.pod_name} not found in namespace {self.namespace}.',
                )
                raise AgentRuntimeDisconnectedError from e

            if self.runtime_container_image is None:
                if self.base_container_image is None:
                    raise ValueError(
                        'Neither runtime container image nor base container image is set'
                    )

                self.send_status_message('STATUS$BUILDING_IMAGE')
                # Initialize a Docker client for building the image
                import docker

                docker_client = docker.from_env()
                self.runtime_builder = DockerRuntimeBuilder(docker_client)

                self.runtime_container_image = build_runtime_image(
                    self.base_container_image,
                    self.runtime_builder,
                    platform=self.config.sandbox.platform,
                    extra_deps=self.config.sandbox.runtime_extra_deps,
                    force_rebuild=self.config.sandbox.force_rebuild_runtime,
                    extra_build_args=self.config.sandbox.runtime_extra_build_args,
                )

            self.log(
                'info', f'Starting runtime with image: {self.runtime_container_image}'
            )
            await call_sync_from_async(self._init_pod)
            self.log(
                'info',
                f'Pod started: {self.pod_name} in namespace {self.namespace}. VSCode URL: {self.vscode_url}',
            )

        # Set up log streaming if needed
        if DEBUG_RUNTIME:
            self.log_streamer = KubernetesLogStreamer(
                self.k8s_client, self.namespace, self.pod_name, self.log
            )

        # Wait for service to be ready
        if not self.attach_to_existing:
            self.log('info', f'Waiting for client to become ready at {self.api_url}...')
            self.send_status_message('STATUS$WAITING_FOR_CLIENT')

        await call_sync_from_async(self._wait_until_alive)

        if not self.attach_to_existing:
            self.log('info', 'Runtime is ready.')
            await call_sync_from_async(self.setup_initial_env)

        self.log(
            'debug',
            f'Pod initialized with plugins: {[plugin.name for plugin in self.plugins]}. VSCode URL: {self.vscode_url}',
        )

        if not self.attach_to_existing:
            self.send_status_message(' ')

        self._runtime_initialized = True

    def _init_pod(self):
        self.log('debug', 'Preparing to start Kubernetes pod...')
        self.send_status_message('STATUS$PREPARING_POD')

        # Find available ports
        self._host_port = self._find_available_port(EXECUTION_SERVER_PORT_RANGE)
        self._container_port = self._host_port
        self._vscode_port = self._find_available_port(VSCODE_PORT_RANGE)
        self._app_ports = [
            self._find_available_port(APP_PORT_RANGE_1),
            self._find_available_port(APP_PORT_RANGE_2),
        ]

        # Set up API URL
        self.api_url = f'{self.config.sandbox.local_runtime_url}:{self._container_port}'

        # Prepare environment variables
        environment = [
            {'name': 'port', 'value': str(self._container_port)},
            {'name': 'PYTHONUNBUFFERED', 'value': '1'},
            {'name': 'VSCODE_PORT', 'value': str(self._vscode_port)},
        ]

        if self.config.debug or DEBUG:
            environment.append({'name': 'DEBUG', 'value': 'true'})

        # Add runtime startup env vars
        for key, value in self.config.sandbox.runtime_startup_env_vars.items():
            environment.append({'name': key, 'value': str(value)})

        # Prepare volume mounts and PVC
        volume_mounts = []
        volumes = []

        # Create a PVC for workspace data
        pvc_name = f'workspace-{self.sid}'

        # Check if PVC already exists, create if it doesn't
        try:
            self.k8s_client.CoreV1Api().read_namespaced_persistent_volume_claim(
                name=pvc_name, namespace=self.namespace
            )
            self.log('debug', f'Using existing PVC: {pvc_name}')
        except Exception:
            # PVC doesn't exist, create it
            pvc_spec = {
                'apiVersion': 'v1',
                'kind': 'PersistentVolumeClaim',
                'metadata': {'name': pvc_name, 'namespace': self.namespace},
                'spec': {
                    'accessModes': ['ReadWriteOnce'],
                    'resources': {
                        'requests': {
                            'storage': getattr(
                                self.config.sandbox, 'pvc_storage_size', '10Gi'
                            )
                        }
                    },
                    'storageClassName': getattr(
                        self.config.sandbox, 'storage_class_name', 'standard'
                    ),
                },
            }

            self.k8s_client.CoreV1Api().create_namespaced_persistent_volume_claim(
                namespace=self.namespace, body=pvc_spec
            )
            self.log('debug', f'Created new PVC: {pvc_name}')

        # Add PVC as a volume
        volumes.append(
            {
                'name': 'workspace-storage',
                'persistentVolumeClaim': {'claimName': pvc_name},
            }
        )

        # Mount the PVC to the workspace path in the container
        workspace_path = self.config.workspace_mount_path_in_sandbox or '/workspace'
        volume_mounts.append(
            {
                'name': 'workspace-storage',
                'mountPath': workspace_path,
                'readOnly': False,
            }
        )

        # Generate command
        command = get_action_execution_server_startup_command(
            server_port=self._container_port,
            plugins=self.plugins,
            app_config=self.config,
            runtime_mode='kubernetes',
        ).split()

        # Create pod specification
        pod_spec = {
            'apiVersion': 'v1',
            'kind': 'Pod',
            'metadata': {
                'name': self.pod_name,
                'namespace': self.namespace,
                'labels': {'app': 'openhands-runtime', 'session-id': self.sid},
            },
            'spec': {
                'containers': [
                    {
                        'name': 'openhands-runtime',
                        'image': self.runtime_container_image,
                        'command': command,
                        'workingDir': '/openhands/code/',
                        'env': environment,
                        'ports': [
                            {'containerPort': self._container_port},
                            {'containerPort': self._vscode_port},
                        ]
                        + [{'containerPort': port} for port in self._app_ports],
                        'volumeMounts': volume_mounts,
                        'resources': {},
                    }
                ],
                'volumes': volumes,
                'restartPolicy': 'Never',
            },
        }

        # Add GPU resources if enabled
        if self.config.sandbox.enable_gpu:
            pod_spec['spec']['containers'][0]['resources'] = {
                'limits': {'nvidia.com/gpu': 1}
            }

        try:
            # Create the namespace if it doesn't exist
            try:
                self.k8s_client.CoreV1Api().create_namespace(
                    body={'metadata': {'name': self.namespace}}
                )
            except Exception:
                # Namespace might already exist
                pass

            # Create the pod
            self.pod = self.k8s_client.CoreV1Api().create_namespaced_pod(
                namespace=self.namespace, body=pod_spec
            )

            # Create service to expose the pod
            service_spec = {
                'apiVersion': 'v1',
                'kind': 'Service',
                'metadata': {
                    'name': f'{self.pod_name}-service',
                    'namespace': self.namespace,
                },
                'spec': {
                    'selector': {'session-id': self.sid},
                    'ports': [
                        {
                            'name': 'exec-server',
                            'port': self._host_port,
                            'targetPort': self._container_port,
                        },
                        {
                            'name': 'vscode',
                            'port': self._vscode_port,
                            'targetPort': self._vscode_port,
                        },
                    ]
                    + [
                        {'name': f'app-{i}', 'port': port, 'targetPort': port}
                        for i, port in enumerate(self._app_ports)
                    ],
                    'type': 'NodePort',  # Or LoadBalancer, depending on your setup
                },
            }

            self.k8s_client.CoreV1Api().create_namespaced_service(
                namespace=self.namespace, body=service_spec
            )

            self.log('debug', f'Pod and service created. Server url: {self.api_url}')
            self.send_status_message('STATUS$POD_STARTED')

        except Exception as e:
            self.log('error', f'Error: Instance {self.pod_name} FAILED to start pod!')
            self.log('error', str(e))
            self.close()
            raise e

    def _attach_to_pod(self):
        """Attach to an existing pod."""
        try:
            # Get pod
            self.pod = self.k8s_client.CoreV1Api().read_namespaced_pod(
                name=self.pod_name, namespace=self.namespace
            )

            # Check if pod is running
            if self.pod.status.phase != 'Running':
                if (
                    self.pod.status.phase == 'Succeeded'
                    or self.pod.status.phase == 'Failed'
                ):
                    # Try to restart the pod
                    self.k8s_client.CoreV1Api().delete_namespaced_pod(
                        name=self.pod_name, namespace=self.namespace
                    )
                    raise Exception(
                        f'Pod {self.pod_name} was in {self.pod.status.phase} state. Deleting to recreate.'
                    )
                else:
                    # For other states like Pending, just wait
                    raise AgentRuntimeDisconnectedError(
                        f'Pod {self.pod_name} is in {self.pod.status.phase} state.'
                    )

            # Extract port information from environment variables
            for container in self.pod.spec.containers:
                if container.name == 'openhands-runtime':
                    for env in container.env:
                        if env.name == 'port':
                            self._host_port = int(env.value)
                            self._container_port = self._host_port
                        elif env.name == 'VSCODE_PORT':
                            self._vscode_port = int(env.value)

            # Get app ports from container ports
            self._app_ports = []
            for container in self.pod.spec.containers:
                if container.name == 'openhands-runtime':
                    for port in container.ports:
                        if (
                            port.container_port != self._host_port
                            and port.container_port != self._vscode_port
                        ):
                            self._app_ports.append(port.container_port)

            # Get service information to determine external access
            service = self.k8s_client.CoreV1Api().read_namespaced_service(
                name=f'{self.pod_name}-service', namespace=self.namespace
            )

            # Determine the API URL
            node_port = None
            for port in service.spec.ports:
                if port.target_port == self._container_port:
                    node_port = port.node_port
                    break

            if node_port:
                # Use NodePort for accessing the service
                self.api_url = f'{self.config.sandbox.local_runtime_url}:{node_port}'
            else:
                # Fallback to in-cluster communication
                self.api_url = f'http://{self.pod_name}-service.{self.namespace}.svc.cluster.local:{self._container_port}'

            self.log(
                'debug',
                f'attached to pod: {self.pod_name} {self._container_port} {self.api_url}',
            )

        except Exception as e:
            self.log('error', f'Failed to attach to pod: {e}')
            raise

    @tenacity.retry(
        stop=tenacity.stop_after_delay(120) | stop_if_should_exit(),
        retry=tenacity.retry_if_exception_type(
            (ConnectionError, requests.exceptions.ConnectionError)
        ),
        reraise=True,
        wait=tenacity.wait_fixed(2),
    )
    def _wait_until_alive(self):
        # Check if pod is still running
        try:
            pod = self.k8s_client.CoreV1Api().read_namespaced_pod(
                name=self.pod_name, namespace=self.namespace
            )

            if pod.status.phase != 'Running':
                raise AgentRuntimeDisconnectedError(
                    f'Pod {self.pod_name} is in {pod.status.phase} state.'
                )
        except Exception as e:
            raise AgentRuntimeNotFoundError(
                f'Pod {self.pod_name} not found in namespace {self.namespace}: {str(e)}'
            )

        # Check if API endpoint is alive
        self.check_if_alive()

    def close(self, rm_all_pods: bool | None = None):
        """Closes the KubernetesRuntime and associated objects."""
        super().close()

        if self.log_streamer:
            self.log_streamer.close()

        if rm_all_pods is None:
            rm_all_pods = getattr(self.config.sandbox, 'rm_all_containers', False)

        if (
            getattr(self.config.sandbox, 'keep_runtime_alive', False)
            or self.attach_to_existing
        ):
            return

        try:
            if rm_all_pods:
                # Delete all pods with label app=openhands-runtime
                pods = self.k8s_client.CoreV1Api().list_namespaced_pod(
                    namespace=self.namespace, label_selector='app=openhands-runtime'
                )
                for pod in pods.items:
                    self.k8s_client.CoreV1Api().delete_namespaced_pod(
                        name=pod.metadata.name, namespace=self.namespace
                    )
                    # Delete corresponding service
                    try:
                        self.k8s_client.CoreV1Api().delete_namespaced_service(
                            name=f'{pod.metadata.name}-service',
                            namespace=self.namespace,
                        )
                    except Exception:
                        pass
            else:
                # Delete only this pod
                try:
                    self.k8s_client.CoreV1Api().delete_namespaced_pod(
                        name=self.pod_name, namespace=self.namespace
                    )
                    self.k8s_client.CoreV1Api().delete_namespaced_service(
                        name=f'{self.pod_name}-service', namespace=self.namespace
                    )
                except Exception:
                    pass
        except Exception as e:
            self.log('error', f'Error cleaning up Kubernetes resources: {e}')

    def _find_available_port(self, port_range, max_attempts=5):
        """Find an available port in the given range."""
        port = port_range[1]
        for _ in range(max_attempts):
            port = find_available_tcp_port(port_range[0], port_range[1])
            if not self._is_port_in_use_k8s(port):
                return port
        return port

    def _is_port_in_use_k8s(self, port):
        """Check if a port is in use by any Kubernetes service."""
        try:
            services = self.k8s_client.CoreV1Api().list_service_for_all_namespaces()
            for service in services.items:
                for service_port in service.spec.ports:
                    if (
                        hasattr(service_port, 'node_port')
                        and service_port.node_port == port
                    ):
                        return True
                    if service_port.port == port:
                        return True
        except Exception:
            # If we can't check, assume it might be in use to be safe
            return True
        return False

    @property
    def vscode_url(self) -> str | None:
        """Generate the VSCode URL for accessing the editor."""
        token = super().get_vscode_token()
        if not token:
            return None

        # Attempt to get node port for VSCode
        try:
            service = self.k8s_client.CoreV1Api().read_namespaced_service(
                name=f'{self.pod_name}-service', namespace=self.namespace
            )

            vscode_node_port = None
            for port in service.spec.ports:
                if port.target_port == self._vscode_port:
                    vscode_node_port = port.node_port
                    break

            if vscode_node_port:
                # Use node IP and NodePort
                nodes = self.k8s_client.CoreV1Api().list_node()
                if nodes.items:
                    node_ip = None
                    for address in nodes.items[0].status.addresses:
                        if address.type == 'ExternalIP':
                            node_ip = address.address
                            break
                    if not node_ip:
                        for address in nodes.items[0].status.addresses:
                            if address.type == 'InternalIP':
                                node_ip = address.address
                                break

                    if node_ip:
                        return f'http://{node_ip}:{vscode_node_port}/?tkn={token}&folder={self.config.workspace_mount_path_in_sandbox}'
        except Exception:
            pass

        # Fallback to localhost if running on the same machine as Kubernetes
        return f'http://localhost:{self._vscode_port}/?tkn={token}&folder={self.config.workspace_mount_path_in_sandbox}'

    @property
    def web_hosts(self):
        """Return a dictionary of web hosts and their ports."""
        hosts = {}

        try:
            service = self.k8s_client.CoreV1Api().read_namespaced_service(
                name=f'{self.pod_name}-service', namespace=self.namespace
            )

            # Map app ports to their node ports
            port_mapping = {}
            for port in service.spec.ports:
                if hasattr(port, 'node_port') and port.node_port:
                    port_mapping[port.target_port] = port.node_port

            # Create URLs using node ports when available
            for app_port in self._app_ports:
                node_port = port_mapping.get(app_port, app_port)
                hosts[f'http://localhost:{node_port}'] = node_port
        except Exception:
            # Fallback to using container ports directly
            for app_port in self._app_ports:
                hosts[f'http://localhost:{app_port}'] = app_port

        return hosts

    def pause(self):
        """Pause the runtime by scaling the pod replicas to 0."""
        try:
            # Simplest approach: delete the pod but keep the service
            self.k8s_client.CoreV1Api().delete_namespaced_pod(
                name=self.pod_name, namespace=self.namespace
            )
            self.log('debug', f'Pod {self.pod_name} paused')
        except Exception as e:
            self.log('error', f'Failed to pause pod: {e}')
            raise

    def resume(self):
        """Resume the runtime by recreating the pod."""
        try:
            # We'll need to recreate the pod with the same configuration
            self._init_pod()
            self.log('debug', f'Pod {self.pod_name} resumed')
            self._wait_until_alive()
        except Exception as e:
            self.log('error', f'Failed to resume pod: {e}')
            raise

    @classmethod
    async def delete(cls, conversation_id: str, namespace: str = 'openhands-runtime'):
        """Class method to delete a pod by conversation ID."""
        try:
            k8s_client = cls._init_k8s_client()
            pod_name = f'{POD_NAME_PREFIX}{conversation_id}'

            # Delete pod
            try:
                k8s_client.CoreV1Api().delete_namespaced_pod(
                    name=pod_name, namespace=namespace
                )
            except Exception:
                pass

            # Delete service
            try:
                k8s_client.CoreV1Api().delete_namespaced_service(
                    name=f'{pod_name}-service', namespace=namespace
                )
            except Exception:
                pass

            # Don't delete PVCs automatically to preserve data
        except Exception as e:
            logger.error(f'Failed to delete Kubernetes resources: {e}')
