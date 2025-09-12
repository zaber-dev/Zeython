import os
from sqlalchemy import create_engine, Column, Integer
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session

# Get the database URL from environment variables or config
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///database.db")

# Create the SQLAlchemy engine
engine = create_engine(DATABASE_URL)

# Create a configured "Session" class
SessionLocal = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))

# Create a global session instance for backward compatibility
session = SessionLocal()

# Create a base class for declarative class definitions
Base = declarative_base()

# Dependency to get the database session
def get_db():
    """
    Dependency to get the database session.
    
    Yields:
        Session: The database session.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Base model class with common methods for all models
class BaseModel(Base):
    """
    Base model class with common methods for all models.
    
    Attributes:
        __abstract__ (bool): Indicates that this class will not be mapped to a table in the database.
        id (int): The primary key of the model.
    """
    __abstract__ = True  # This class will not be mapped to a table in the database

    id = Column(Integer, primary_key=True, index=True)  # Every model will have an id column

    @classmethod
    def create(cls, db_session=None, **kwargs):
        """
        Create a new instance of the model and add it to the session.

        Args:
            db_session (Session, optional): The database session. Defaults to None.
            **kwargs: The attributes of the model.

        Returns:
            BaseModel: The created instance of the model.
        """
        if db_session is None:
            db_session = SessionLocal()
        instance = cls(**kwargs)
        db_session.add(instance)
        db_session.commit()
        db_session.refresh(instance)
        return instance

    @classmethod
    def get(cls, id, db_session=None):
        """
        Get an instance of the model by ID.

        Args:
            id (int): The ID of the model instance.
            db_session (Session, optional): The database session. Defaults to None.

        Returns:
            BaseModel: The instance of the model, or None if not found.
        """
        if db_session is None:
            db_session = SessionLocal()
        return db_session.query(cls).filter(cls.id == id).first()

    @classmethod
    def all(cls, db_session=None):
        """
        Get all instances of the model.

        Args:
            db_session (Session, optional): The database session. Defaults to None.

        Returns:
            list: A list of all instances of the model.
        """
        if db_session is None:
            db_session = SessionLocal()
        return db_session.query(cls).all()

    @classmethod
    def update(cls, id, db_session=None, **kwargs):
        """
        Update an instance of the model by ID with the given keyword arguments.

        Args:
            id (int): The ID of the model instance.
            db_session (Session, optional): The database session. Defaults to None.
            **kwargs: The attributes to update.

        Returns:
            BaseModel: The updated instance of the model, or None if not found.
        """
        if db_session is None:
            db_session = SessionLocal()
        instance = db_session.query(cls).filter(cls.id == id).first()
        if instance:
            for key, value in kwargs.items():
                setattr(instance, key, value)
            db_session.commit()
            db_session.refresh(instance)
        return instance

    @classmethod
    def delete(cls, id, db_session=None):
        """
        Delete an instance of the model by ID.

        Args:
            id (int): The ID of the model instance.
            db_session (Session, optional): The database session. Defaults to None.

        Returns:
            BaseModel: The deleted instance of the model, or None if not found.
        """
        if db_session is None:
            db_session = SessionLocal()
        instance = db_session.query(cls).filter(cls.id == id).first()
        if instance:
            db_session.delete(instance)
            db_session.commit()
        return instance

    @classmethod
    def filter(cls, db_session=None, **kwargs):
        """
        Filter instances of the model by the given keyword arguments.

        Args:
            db_session (Session, optional): The database session. Defaults to None.
            **kwargs: The attributes to filter by.

        Returns:
            list: A list of instances of the model that match the filter criteria.
        """
        if db_session is None:
            db_session = SessionLocal()
        query = db_session.query(cls)
        for key, value in kwargs.items():
            query = query.filter(getattr(cls, key) == value)
        return query.all()
    
    @classmethod
    def exists(cls, id, db_session=None):
        """
        Check if an instance of the model exists by ID.

        Args:
            id (int): The ID of the model instance.
            db_session (Session, optional): The database session. Defaults to None.

        Returns:
            bool: True if the instance exists, False otherwise.
        """
        if db_session is None:
            db_session = SessionLocal()
        return db_session.query(cls).filter(cls.id == id).exists()