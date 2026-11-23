from sqladmin import ModelView
from sqlalchemy import Column, BigInteger, DateTime, Enum, func

from enums.staff_role import StaffRole
from models.base import Base


class StaffMember(Base):
    """Admins and moderators added by an owner. Owners themselves come from ADMIN_ID_LIST."""
    __tablename__ = 'staff_members'

    telegram_id = Column(BigInteger, primary_key=True, autoincrement=False)
    role = Column(Enum(StaffRole), nullable=False)
    created_at = Column(DateTime(timezone=True), default=func.now())


class StaffMemberAdmin(ModelView, model=StaffMember):
    name = "Staff member"
    name_plural = "Staff"
    column_list = [StaffMember.telegram_id, StaffMember.role, StaffMember.created_at]
    form_columns = [StaffMember.telegram_id, StaffMember.role]
    can_export = False
