from fastapi import APIRouter, Depends

from modules.marketingAds import all_marketingAds_sp, upsert_marketingAds_sp
from security.worker_key import require_worker_key

router = APIRouter()

# Worker-only: marketingAdsSyncWorker (smartloans_workers) lists pending ads and
# writes Meta's lookup results. The webhook creates pending rows in-process
# (modules.marketingAds.ensure_pending), not through this route.

with open("./docs_description/marketingAds.txt", "r") as file:
    marketingAds_docstring = file.read()
@router.post("/marketingAds", summary="ensure / resolve Marketing Ads", description=marketingAds_docstring)
def marketingAds(json: dict, _: str = Depends(require_worker_key)):
    return upsert_marketingAds_sp(json)


with open("./docs_description/marketingAds_all.txt", "r") as file:
    marketingAds_all_docstring = file.read()
@router.post("/all_marketingAds", summary="all Marketing Ads", description=marketingAds_all_docstring)
def all_marketingAds(json: dict, _: str = Depends(require_worker_key)):
    return all_marketingAds_sp(json)
