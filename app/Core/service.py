"""
Service interface and base classes for the modular MVC framework.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import threading
import logging


class ServiceInterface(ABC):
    """
    Abstract base class for all services in the application.
    
    All services must implement this interface to be managed by the ServiceManager.
    """
    
    def __init__(self, name: str, config: Dict[str, Any] = None):
        """
        Initialize the service.
        
        Args:
            name (str): The name of the service
            config (Dict[str, Any], optional): Service configuration
        """
        self.name = name
        self.config = config or {}
        self.is_running = False
        self._thread = None
        self.logger = logging.getLogger(f"service.{name}")
    
    @abstractmethod
    def start(self) -> bool:
        """
        Start the service.
        
        Returns:
            bool: True if service started successfully, False otherwise
        """
        pass
    
    @abstractmethod
    def stop(self) -> bool:
        """
        Stop the service.
        
        Returns:
            bool: True if service stopped successfully, False otherwise
        """
        pass
    
    @abstractmethod
    def is_enabled(self) -> bool:
        """
        Check if the service is enabled based on configuration.
        
        Returns:
            bool: True if service should be started, False otherwise
        """
        pass
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get the current status of the service.
        
        Returns:
            Dict[str, Any]: Service status information
        """
        return {
            'name': self.name,
            'is_running': self.is_running,
            'is_enabled': self.is_enabled(),
            'thread_alive': self._thread.is_alive() if self._thread else False
        }


class ThreadedService(ServiceInterface):
    """
    Base class for services that run in their own thread.
    """
    
    def start(self) -> bool:
        """
        Start the service in a separate thread.
        
        Returns:
            bool: True if service started successfully, False otherwise
        """
        if not self.is_enabled():
            self.logger.info(f"Service {self.name} is disabled")
            return False
            
        if self.is_running:
            self.logger.warning(f"Service {self.name} is already running")
            return True
        
        try:
            self._thread = threading.Thread(target=self._run, name=f"service-{self.name}")
            self._thread.daemon = True
            self._thread.start()
            self.is_running = True
            self.logger.info(f"Service {self.name} started successfully")
            return True
        except Exception as e:
            self.logger.error(f"Failed to start service {self.name}: {e}")
            return False
    
    def stop(self) -> bool:
        """
        Stop the service.
        
        Returns:
            bool: True if service stopped successfully, False otherwise
        """
        if not self.is_running:
            return True
        
        try:
            self.is_running = False
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=5.0)
            self.logger.info(f"Service {self.name} stopped successfully")
            return True
        except Exception as e:
            self.logger.error(f"Failed to stop service {self.name}: {e}")
            return False
    
    @abstractmethod
    def _run(self):
        """
        The main execution method for the service.
        This method will be called in a separate thread.
        """
        pass