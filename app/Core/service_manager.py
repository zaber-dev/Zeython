"""
Service Manager for the modular MVC framework.
Handles registration, lifecycle management, and coordination of services.
"""

import os
import logging
from typing import Dict, List, Type, Any, Optional
from .service import ServiceInterface


class ServiceManager:
    """
    Manages the lifecycle of all services in the application.
    
    Provides service registration, startup, shutdown, and status monitoring.
    """
    
    def __init__(self):
        """Initialize the service manager."""
        self.services: Dict[str, ServiceInterface] = {}
        self.service_classes: Dict[str, Type[ServiceInterface]] = {}
        self.logger = logging.getLogger("service_manager")
        
    def register_service_class(self, service_class: Type[ServiceInterface], name: str = None):
        """
        Register a service class for later instantiation.
        
        Args:
            service_class (Type[ServiceInterface]): The service class to register
            name (str, optional): The name to register the service under. 
                                 If None, uses the class name.
        """
        service_name = name or service_class.__name__.lower().replace('service', '')
        self.service_classes[service_name] = service_class
        self.logger.debug(f"Registered service class: {service_name}")
    
    def add_service(self, service: ServiceInterface):
        """
        Add a service instance to the manager.
        
        Args:
            service (ServiceInterface): The service instance to add
        """
        self.services[service.name] = service
        self.logger.debug(f"Added service: {service.name}")
    
    def create_service(self, service_name: str, config: Dict[str, Any] = None) -> Optional[ServiceInterface]:
        """
        Create a service instance from a registered service class.
        
        Args:
            service_name (str): The name of the service to create
            config (Dict[str, Any], optional): Configuration for the service
            
        Returns:
            Optional[ServiceInterface]: The created service instance or None if not found
        """
        if service_name not in self.service_classes:
            self.logger.error(f"Service class not found: {service_name}")
            return None
        
        try:
            service_class = self.service_classes[service_name]
            service = service_class(service_name, config)
            self.add_service(service)
            return service
        except Exception as e:
            self.logger.error(f"Failed to create service {service_name}: {e}")
            return None
    
    def start_service(self, service_name: str) -> bool:
        """
        Start a specific service.
        
        Args:
            service_name (str): The name of the service to start
            
        Returns:
            bool: True if service started successfully, False otherwise
        """
        if service_name not in self.services:
            self.logger.error(f"Service not found: {service_name}")
            return False
        
        return self.services[service_name].start()
    
    def stop_service(self, service_name: str) -> bool:
        """
        Stop a specific service.
        
        Args:
            service_name (str): The name of the service to stop
            
        Returns:
            bool: True if service stopped successfully, False otherwise
        """
        if service_name not in self.services:
            self.logger.error(f"Service not found: {service_name}")
            return False
        
        return self.services[service_name].stop()
    
    def start_all_enabled_services(self) -> bool:
        """
        Start all enabled services.
        
        Returns:
            bool: True if all enabled services started successfully, False otherwise
        """
        success = True
        for service in self.services.values():
            if service.is_enabled():
                if not service.start():
                    success = False
        return success
    
    def stop_all_services(self) -> bool:
        """
        Stop all running services.
        
        Returns:
            bool: True if all services stopped successfully, False otherwise
        """
        success = True
        for service in self.services.values():
            if not service.stop():
                success = False
        return success
    
    def get_service_status(self, service_name: str = None) -> Dict[str, Any]:
        """
        Get the status of services.
        
        Args:
            service_name (str, optional): Name of specific service. If None, returns all services.
            
        Returns:
            Dict[str, Any]: Service status information
        """
        if service_name:
            if service_name in self.services:
                return self.services[service_name].get_status()
            else:
                return {'error': f'Service not found: {service_name}'}
        
        return {
            'services': {name: service.get_status() for name, service in self.services.items()},
            'total_services': len(self.services),
            'running_services': len([s for s in self.services.values() if s.is_running]),
            'enabled_services': len([s for s in self.services.values() if s.is_enabled()])
        }
    
    def get_service(self, service_name: str) -> Optional[ServiceInterface]:
        """
        Get a service instance by name.
        
        Args:
            service_name (str): The name of the service
            
        Returns:
            Optional[ServiceInterface]: The service instance or None if not found
        """
        return self.services.get(service_name)
    
    def wait_for_services(self):
        """
        Block until all running services complete.
        """
        for service in self.services.values():
            if service.is_running and service._thread and service._thread.is_alive():
                service._thread.join()
    
    def list_available_services(self) -> List[str]:
        """
        Get a list of all available service classes.
        
        Returns:
            List[str]: List of service names
        """
        return list(self.service_classes.keys())
    
    def list_registered_services(self) -> List[str]:
        """
        Get a list of all registered service instances.
        
        Returns:
            List[str]: List of service names
        """
        return list(self.services.keys())


# Global service manager instance
service_manager = ServiceManager()