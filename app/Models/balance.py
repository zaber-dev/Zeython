from sqlalchemy import Column, Integer, Float, ForeignKey, String, Boolean
from sqlalchemy.orm import relationship
from database.db import BaseModel, session
from app.Models.base_model import EnhancedBaseModel, ValidationError
from typing import Dict, Any, Optional, List
import logging

logger = logging.getLogger(__name__)

# Define the Balance model class, inheriting from EnhancedBaseModel
class Balance(EnhancedBaseModel):
    """
    Balance model representing the balance of a user.

    Enhanced balance model with audit trails, validation, and business logic.

    Attributes:
        __tablename__ (str): The name of the table in the database.
        user_id (int): Foreign key referencing the user's ID.
        amount (float): The balance amount (must be >= 0 for most operations).
        currency (str): Currency code (default: USD).
        is_frozen (bool): Whether the balance is frozen from transactions.
        minimum_balance (float): Minimum allowed balance.
        
    Inherited from EnhancedBaseModel:
        id (int): Primary key
        created_at (datetime): When the balance was created
        updated_at (datetime): When the balance was last updated
        created_by (str): Who created the balance
        updated_by (str): Who last updated the balance
        deleted_at (datetime): When the balance was soft deleted
        deleted_by (str): Who deleted the balance
        is_deleted (bool): Whether the balance is soft deleted
    """
    __tablename__ = 'balances'  # Define the table name

    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, unique=True)  # One balance per user
    amount = Column(Float, nullable=False, default=0.0)  # Balance amount
    currency = Column(String(3), nullable=False, default='USD')  # Currency code
    is_frozen = Column(Boolean, default=False, nullable=False)  # Whether balance is frozen
    minimum_balance = Column(Float, default=0.0, nullable=False)  # Minimum allowed balance
    
    def __init__(self, **kwargs):
        # Set default amount if not provided
        if 'amount' not in kwargs:
            kwargs['amount'] = 0.0
        
        super().__init__(**kwargs)
    
    def is_sufficient(self, amount: float) -> bool:
        """Check if balance is sufficient for a withdrawal."""
        return (self.amount - amount) >= self.minimum_balance
    
    def can_transact(self) -> bool:
        """Check if transactions are allowed on this balance."""
        return not self.is_frozen and not self.is_deleted
    
    def freeze(self, user_id: str = None):
        """Freeze the balance to prevent transactions."""
        self.is_frozen = True
        if user_id:
            self.updated_by = user_id
        session.commit()
    
    def unfreeze(self, user_id: str = None):
        """Unfreeze the balance to allow transactions."""
        self.is_frozen = False
        if user_id:
            self.updated_by = user_id
        session.commit()
    
    def deposit(self, amount: float, user_id: str = None) -> bool:
        """
        Deposit amount to balance.
        
        Args:
            amount: Amount to deposit (must be positive)
            user_id: User making the transaction
            
        Returns:
            True if successful, False otherwise
            
        Raises:
            ValidationError: If amount is invalid or balance is frozen
        """
        if amount <= 0:
            raise ValidationError('amount', 'Deposit amount must be positive')
        
        if not self.can_transact():
            raise ValidationError('balance', 'Balance is frozen or deleted')
        
        self.amount += amount
        if user_id:
            self.updated_by = user_id
        
        session.commit()
        logger.info(f"Deposited {amount} to balance {self.id}. New balance: {self.amount}")
        return True
    
    def withdraw(self, amount: float, user_id: str = None, allow_overdraft: bool = False) -> bool:
        """
        Withdraw amount from balance.
        
        Args:
            amount: Amount to withdraw (must be positive)
            user_id: User making the transaction
            allow_overdraft: Whether to allow withdrawal below minimum balance
            
        Returns:
            True if successful, False otherwise
            
        Raises:
            ValidationError: If amount is invalid, insufficient funds, or balance is frozen
        """
        if amount <= 0:
            raise ValidationError('amount', 'Withdrawal amount must be positive')
        
        if not self.can_transact():
            raise ValidationError('balance', 'Balance is frozen or deleted')
        
        if not allow_overdraft and not self.is_sufficient(amount):
            raise ValidationError('amount', 'Insufficient balance')
        
        self.amount -= amount
        if user_id:
            self.updated_by = user_id
        
        session.commit()
        logger.info(f"Withdrew {amount} from balance {self.id}. New balance: {self.amount}")
        return True
    
    def transfer_to(self, target_balance: 'Balance', amount: float, user_id: str = None) -> bool:
        """
        Transfer amount to another balance.
        
        Args:
            target_balance: Target balance instance
            amount: Amount to transfer
            user_id: User making the transaction
            
        Returns:
            True if successful, False otherwise
            
        Raises:
            ValidationError: If transfer fails
        """
        if amount <= 0:
            raise ValidationError('amount', 'Transfer amount must be positive')
        
        if not self.can_transact():
            raise ValidationError('source_balance', 'Source balance is frozen or deleted')
        
        if not target_balance.can_transact():
            raise ValidationError('target_balance', 'Target balance is frozen or deleted')
        
        if not self.is_sufficient(amount):
            raise ValidationError('amount', 'Insufficient balance for transfer')
        
        # Perform transfer
        self.amount -= amount
        target_balance.amount += amount
        
        if user_id:
            self.updated_by = user_id
            target_balance.updated_by = user_id
        
        session.commit()
        logger.info(f"Transferred {amount} from balance {self.id} to balance {target_balance.id}")
        return True
    
    @classmethod
    def get_by_user_id(cls, user_id: int) -> Optional['Balance']:
        """Get balance by user ID."""
        return cls.find_one_by(user_id=user_id)
    
    @classmethod
    def create_for_user(cls, user_id: int, initial_amount: float = 0.0, 
                       currency: str = 'USD', **kwargs) -> 'Balance':
        """
        Create a balance for a user.
        
        Args:
            user_id: User ID
            initial_amount: Initial balance amount
            currency: Currency code
            **kwargs: Additional balance attributes
            
        Returns:
            Balance instance
            
        Raises:
            ValidationError: If user already has a balance
        """
        existing = cls.get_by_user_id(user_id)
        if existing and not existing.is_deleted:
            raise ValidationError('user_id', 'User already has a balance')
        
        return cls.create(
            user_id=user_id,
            amount=initial_amount,
            currency=currency,
            **kwargs
        )
    
    @classmethod
    def get_total_system_balance(cls) -> float:
        """Get total balance across all users."""
        balances = cls.find_by(is_deleted=False)
        return sum(balance.amount for balance in balances)
    
    @classmethod
    def get_balances_by_currency(cls, currency: str = 'USD') -> List['Balance']:
        """Get all balances for a specific currency."""
        return cls.find_by(currency=currency, is_deleted=False)

    def __repr__(self):
        """
        String representation of the Balance model.

        Returns:
            str: A string representation of the Balance instance.
        """
        return f"<Balance(id={self.id}, user_id={self.user_id}, amount={self.amount} {self.currency})>"
    
# Example usage of the Balance model

# Create a new balance instance for a user with user_id 1
# balance = Balance.create(user_id=1, amount=100.0)

# Get a balance instance by ID
# balance_instance = Balance.get(balance.id)
# print(balance_instance)  # Output: <Balance(user_id=1, amount=100.0)>

# Get all balance instances
# all_balances = Balance.all()
# print(all_balances)  # Output: [<Balance(user_id=1, amount=100.0)>]

# Update a balance instance by ID
# updated_balance = Balance.update(balance.id, amount=150.0)
# print(updated_balance)  # Output: <Balance(user_id=1, amount=150.0)>

# Delete a balance instance by ID
# deleted_balance = Balance.delete(balance.id)
# print(deleted_balance)  # Output: <Balance(user_id=1, amount=150.0)>

# Filter balance instances by user_id
# filtered_balances = Balance.filter(user_id=1)
# print(filtered_balances)  # Output: [<Balance(user_id=1, amount=150.0)>]

# Check if a balance instance exists by ID
# exists = Balance.exists(balance.id)
# print(exists)  # Output: True