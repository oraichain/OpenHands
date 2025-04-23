from unittest.mock import MagicMock, patch

import docker
import pytest

from openhands.runtime.impl.docker.containers import stop_all_containers


@pytest.fixture
def mock_docker_client():
    with patch('docker.from_env') as mock_client:
        yield mock_client.return_value


def test_stop_all_containers_no_containers(mock_docker_client):
    # Arrange
    mock_docker_client.containers.list.return_value = []

    # Act
    stop_all_containers('test-prefix')

    # Assert
    mock_docker_client.containers.list.assert_called_once_with(
        all=True, filters={'name': 'test-prefix'}
    )
    # No containers to stop, so no stop/remove calls


def test_stop_all_containers_with_containers(mock_docker_client):
    # Arrange
    container1 = MagicMock()
    container1.name = 'test-prefix-container1'
    container2 = MagicMock()
    container2.name = 'test-prefix-container2'
    mock_docker_client.containers.list.return_value = [container1, container2]

    # Act
    stop_all_containers('test-prefix')

    # Assert
    mock_docker_client.containers.list.assert_called_once_with(
        all=True, filters={'name': 'test-prefix'}
    )
    container1.stop.assert_called_once()
    container1.remove.assert_called_once()
    container2.stop.assert_called_once()
    container2.remove.assert_called_once()


def test_stop_all_containers_with_api_error(mock_docker_client):
    # Arrange
    container = MagicMock()
    container.name = 'test-prefix-container'
    container.stop.side_effect = docker.errors.APIError('API Error')
    mock_docker_client.containers.list.return_value = [container]

    # Act
    stop_all_containers('test-prefix')

    # Assert
    mock_docker_client.containers.list.assert_called_once_with(
        all=True, filters={'name': 'test-prefix'}
    )
    container.stop.assert_called_once()
    # Should not call remove if stop fails
    container.remove.assert_not_called()


def test_stop_all_containers_with_not_found_error(mock_docker_client):
    # Arrange
    container = MagicMock()
    container.name = 'test-prefix-container'
    container.stop.side_effect = docker.errors.NotFound('Container not found')
    mock_docker_client.containers.list.return_value = [container]

    # Act
    stop_all_containers('test-prefix')

    # Assert
    mock_docker_client.containers.list.assert_called_once_with(
        all=True, filters={'name': 'test-prefix'}
    )
    container.stop.assert_called_once()
    # Should not call remove if stop fails
    container.remove.assert_not_called()


def test_stop_all_containers_with_remove_error(mock_docker_client):
    # Arrange
    container = MagicMock()
    container.name = 'test-prefix-container'
    container.remove.side_effect = docker.errors.APIError('Remove error')
    mock_docker_client.containers.list.return_value = [container]

    # Act
    stop_all_containers('test-prefix')

    # Assert
    mock_docker_client.containers.list.assert_called_once_with(
        all=True, filters={'name': 'test-prefix'}
    )
    container.stop.assert_called_once()
    container.remove.assert_called_once()
    # Should continue execution even if remove fails


def test_stop_all_containers_with_docker_not_found_error(mock_docker_client):
    # Arrange
    mock_docker_client.containers.list.side_effect = docker.errors.NotFound(
        'Docker not found'
    )

    # Act
    stop_all_containers('test-prefix')

    # Assert
    mock_docker_client.containers.list.assert_called_once_with(
        all=True, filters={'name': 'test-prefix'}
    )
    # Should handle the error gracefully


def test_stop_all_containers_with_empty_prefix(mock_docker_client):
    # Arrange
    mock_docker_client.containers.list.return_value = []

    # Act
    stop_all_containers('')

    # Assert
    mock_docker_client.containers.list.assert_called_once_with(
        all=True, filters={'name': ''}
    )


def test_stop_all_containers_with_none_prefix(mock_docker_client):
    # Arrange
    mock_docker_client.containers.list.return_value = []

    # Act
    stop_all_containers(None)

    # Assert
    mock_docker_client.containers.list.assert_called_once_with(
        all=True, filters={'name': None}
    )


def test_stop_all_containers_with_special_characters_prefix(mock_docker_client):
    # Arrange
    mock_docker_client.containers.list.return_value = []

    # Act
    stop_all_containers('test-prefix!@#$%^&*()')

    # Assert
    mock_docker_client.containers.list.assert_called_once_with(
        all=True, filters={'name': 'test-prefix!@#$%^&*()'}
    )


def test_stop_all_containers_with_very_long_prefix(mock_docker_client):
    # Arrange
    long_prefix = 'a' * 1000
    mock_docker_client.containers.list.return_value = []

    # Act
    stop_all_containers(long_prefix)

    # Assert
    mock_docker_client.containers.list.assert_called_once_with(
        all=True, filters={'name': long_prefix}
    )
