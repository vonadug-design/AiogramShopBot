from sqladmin import ModelView
from sqlalchemy import Column, Integer, String, Text, DateTime, UniqueConstraint, func

from models.base import Base


class TextOverride(Base):
    """A bot text (or the welcome photo) changed by an admin in the bot, per language."""
    __tablename__ = 'text_overrides'
    __table_args__ = (UniqueConstraint('language', 'entity', 'key', name='uq_text_overrides'),)

    id = Column(Integer, primary_key=True)
    language = Column(String(8), nullable=False)
    entity = Column(String(16), nullable=False)
    key = Column(String(64), nullable=False)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())


class TextOverrideAdmin(ModelView, model=TextOverride):
    name = "Text"
    name_plural = "Texts"
    column_list = [TextOverride.language, TextOverride.entity, TextOverride.key, TextOverride.value]
    column_searchable_list = [TextOverride.key, TextOverride.value]
    can_export = False
