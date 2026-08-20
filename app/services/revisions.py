from __future__ import annotations

import json
import uuid
from typing import Any

from app.db import execute, fetchall, fetchone, now_iso
from . import editor, timeline


def create_revision(clip_id: str, label: str='Checkpoint') -> dict[str,Any]:
    data=timeline.get_or_create_timeline(clip_id); state=editor.get_or_create_edit_state(clip_id)
    row=fetchone('SELECT COALESCE(MAX(revision),0) n FROM clip_revisions WHERE clip_id=?',(clip_id,)); rev=int(row['n'] or 0)+1
    rid=uuid.uuid4().hex
    execute('INSERT INTO clip_revisions(id,clip_id,revision,label,timeline_json,edit_state_json,created_at) VALUES(?,?,?,?,?,?,?)',(rid,clip_id,rev,(label or 'Checkpoint')[:120],json.dumps(data,ensure_ascii=False),json.dumps(state,ensure_ascii=False),now_iso()))
    return {"id":rid,"clip_id":clip_id,"revision":rev,"label":label,"created_at":now_iso()}


def list_revisions(clip_id:str)->list[dict[str,Any]]:
    return [dict(r) for r in fetchall('SELECT id,clip_id,revision,label,created_at FROM clip_revisions WHERE clip_id=? ORDER BY revision DESC',(clip_id,))]


def restore_revision(clip_id:str, revision:int)->dict[str,Any]:
    row=fetchone('SELECT * FROM clip_revisions WHERE clip_id=? AND revision=?',(clip_id,int(revision)))
    if not row: raise ValueError('revisão não encontrada')
    # Create a checkpoint of the current state before restoring.
    create_revision(clip_id,f'Antes de restaurar r{revision}')
    data=json.loads(row['timeline_json']); state=json.loads(row['edit_state_json'])
    timeline.save_timeline(clip_id,data); editor.save_edit_state(clip_id,state)
    return {"restored":int(revision),"timeline":data,"edit_state":state}
