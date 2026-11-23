from pydantic import BaseModel
from sqladmin import ModelView
from sqlalchemy import Integer, Column, String, ForeignKey, JSON
from sqlalchemy.orm import relationship

from models.base import Base


class Category(Base):
    __tablename__ = 'categories'

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, index=True)
    # Categories form a tree of any depth; items live in any category of it (usually a leaf).
    parent_id = Column(Integer, ForeignKey('categories.id', ondelete='SET NULL'), nullable=True, index=True)
    media_id = Column(String, nullable=False)
    # Manual order inside one level of the tree (smaller first), then by name.
    position = Column(Integer, nullable=False, default=0, server_default='0')
    # Text shown above this category's contents, per language: {"ru": "...", "en": "..."}.
    descriptions = Column(JSON, nullable=True)
    items = relationship("Item", back_populates="category")
    cart_items = relationship("CartItem", back_populates="category")

    def __repr__(self):
        return self.name


class CategoryDTO(BaseModel):
    id: int | None = None
    name: str | None = None
    media_id: str | None = None
    parent_id: int | None = None
    position: int = 0
    descriptions: dict | None = None


class CategoryAdmin(ModelView, model=Category):
    name = "Category"
    name_plural = "Categories"
    column_searchable_list = [Category.name]
    column_sortable_list = [Category.id, Category.name]
    column_exclude_list = [Category.items,
                           Category.media_id,
                           Category.cart_items,
                           Category.descriptions]
    can_delete = False
    can_edit = True
    can_create = True
    can_export = False
