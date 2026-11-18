from fastapi import APIRouter, Depends

from modules.marketingLeadAttributions import all_marketingLeadAttributions_sp, one_marketingLeadAttributions_sp
from security.worker_key import require_worker_key

router = APIRouter()

# No create route: rows are written in-process by the WhatsApp webhook, because a
# public route would let anyone forge attribution. Reads return customer phones,
# so both need the worker key until the backend has real user auth.

with open("./docs_description/marketingLeadAttributions_all.txt", "r") as file:
    marketingLeadAttributions_all_docstring = file.read()
@router.post("/all_marketingLeadAttributions", summary="all Marketing Lead Attributions", description=marketingLeadAttributions_all_docstring)
def all_marketingLeadAttributions(json: dict, _: str = Depends(require_worker_key)):
    return all_marketingLeadAttributions_sp(json)


with open("./docs_description/marketingLeadAttributions_one.txt", "r") as file:
    marketingLeadAttributions_one_docstring = file.read()
@router.post("/one_marketingLeadAttributions", summary="one Marketing Lead Attribution", description=marketingLeadAttributions_one_docstring)
def one_marketingLeadAttributions(json: dict, _: str = Depends(require_worker_key)):
    return one_marketingLeadAttributions_sp(json)
