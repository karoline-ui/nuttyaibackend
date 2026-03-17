"""
app/api/v1/__init__.py - Router principal da API v1
"""
from fastapi import APIRouter
from app.api.v1 import (
    auth, workspaces, conversations, messages,
    appointments, campaigns, flows, connections,
    media, webhooks, contacts, knowledge_base, dashboard
)

router = APIRouter()

router.include_router(auth.router,          prefix="/auth",          tags=["Auth"])
router.include_router(workspaces.router,    prefix="/workspaces",    tags=["Workspaces"])
router.include_router(contacts.router,      prefix="/contacts",      tags=["Contacts"])
router.include_router(conversations.router, prefix="/conversations",  tags=["Conversations"])
router.include_router(messages.router,      prefix="/messages",       tags=["Messages"])
router.include_router(appointments.router,  prefix="/appointments",   tags=["Appointments"])
router.include_router(campaigns.router,     prefix="/campaigns",      tags=["Campaigns"])
router.include_router(flows.router,         prefix="/flows",          tags=["Flows"])
router.include_router(connections.router,   prefix="/connections",    tags=["Connections"])
router.include_router(media.router,         prefix="/media",          tags=["Media"])
router.include_router(knowledge_base.router,prefix="/knowledge",      tags=["Knowledge Base"])
router.include_router(webhooks.router,      prefix="/webhooks",       tags=["Webhooks"])
router.include_router(dashboard.router,     prefix="/dashboard",      tags=["Dashboard"])
