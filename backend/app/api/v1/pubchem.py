from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException, Response, status

router = APIRouter(prefix="/pubchem", tags=["pubchem"])

PUBCHEM_SDF_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/record/SDF/?record_type=3d"


@router.get("/molecule/{cid}")
async def get_molecule_sdf(cid: int) -> Response:
    """Proxy a compound's 3D SDF record from PubChem.

    Public chemical structure data, not PHI — no auth required. This exists so the
    browser never calls PubChem directly (avoids CORS, and PubChem's usage policy
    prefers server-to-server traffic over ad-hoc browser requests).
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.get(PUBCHEM_SDF_URL.format(cid=cid))
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail="Could not reach PubChem"
            ) from exc

    if resp.status_code == status.HTTP_404_NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No 3D conformer available for CID {cid}",
        )
    if resp.status_code != status.HTTP_200_OK:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"PubChem returned {resp.status_code}",
        )

    return Response(content=resp.text, media_type="chemical/x-mdl-sdfile")
