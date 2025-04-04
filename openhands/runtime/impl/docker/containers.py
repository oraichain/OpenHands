import docker
import os
import json
import random
from typing import List

def _get_docker_clients() -> List[docker.DockerClient]:
    try:
        from urllib3.exceptions import MaxRetryError
        from requests.exceptions import ConnectionError, RequestException
        
        remote_docker_urls = os.getenv('API_REMOTE_DOCKER', '')
        try:
            docker_hosts = json.loads(remote_docker_urls)
        except Exception:
            docker_hosts = [url.strip() for url in remote_docker_urls.split(',') if url.strip()]
            
        clients = []
        if not docker_hosts:
            clients.append(docker.from_env())
            return clients
            
        # Try each host with better error handling
        all_hosts = list(docker_hosts)
        random.shuffle(all_hosts)
        
        for host in all_hosts:
            try:
                client = docker.DockerClient(base_url=host, timeout=5)
                # Verify connection is working
                client.ping()
                client.version()
                client._selected_docker_host = host
                clients.append(client)
                print(f'Successfully connected to Docker host: {host}')
            except (ConnectionError, MaxRetryError, RequestException) as e:
                print(f'Failed to connect to Docker host {host}: {str(e)}')
                continue
            except Exception as e:
                print(f'Unexpected error with Docker host {host}: {str(e)}')
                continue
                
        if not clients:
            print('All remote Docker hosts failed, using local Docker')
            clients.append(docker.from_env())
            
        return clients
    except Exception as ex:
        print(f'Docker client initialization failed: {str(ex)}')
        return [docker.from_env()]


def stop_all_containers(prefix: str):
    clients = _get_docker_clients()
    try:
        for docker_client in clients:
            try:
                containers = docker_client.containers.list(all=True)
                for container in containers:
                    try:
                        if container.name.startswith(prefix):
                            container.stop()
                    except (docker.errors.APIError, docker.errors.NotFound):
                        pass
            except docker.errors.NotFound:
                pass
    finally:
        for client in clients:
            try:
                client.close()
            except:
                pass