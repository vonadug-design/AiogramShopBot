from sqladmin import ModelView
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, func

from models.base import Base


class ApironeInvoice(Base):
    __tablename__ = 'apirone_invoices'

    id = Column(Integer, primary_key=True)
    invoice_id = Column(String, nullable=False, unique=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    currency = Column(String, nullable=False)
    fiat_amount = Column(Float, nullable=False)
    status = Column(String, nullable=False, default="created")
    credited = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), default=func.now())

    def __repr__(self):
        return f"Apirone {self.invoice_id}"


class ApironeInvoiceAdmin(ModelView, model=ApironeInvoice):
    can_create = False
    can_delete = False
    can_edit = False
    column_list = [ApironeInvoice.id, ApironeInvoice.invoice_id, ApironeInvoice.user_id, ApironeInvoice.currency,
                   ApironeInvoice.fiat_amount, ApironeInvoice.status, ApironeInvoice.credited,
                   ApironeInvoice.created_at]
    name = "Apirone invoice"
    name_plural = "Apirone invoices"
