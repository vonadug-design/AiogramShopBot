from sqladmin import ModelView
from sqlalchemy import Column, Integer, String

from models.base import Base


class CustomButton(Base):
    """A link button (channel, chat, site) shown under the welcome message of the main bot and the storefronts."""
    __tablename__ = 'custom_buttons'

    id = Column(Integer, primary_key=True)
    text = Column(String(64), nullable=False)
    url = Column(String(512), nullable=False)
    position = Column(Integer, nullable=False, default=0, server_default='0')


class CustomButtonAdmin(ModelView, model=CustomButton):
    name = "Link button"
    name_plural = "Link buttons"
    column_list = [CustomButton.position, CustomButton.text, CustomButton.url]
    can_export = False
