from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from . import timeline, editor, revisions


def _remove_generated(data:dict[str,Any],types:set[str])->int:
    removed=0
    for tr in data.get('tracks') or []:
        if tr.get('type') not in types: continue
        old=tr.get('items') or []; new=[x for x in old if x.get('generatedBy')!='auto-edit']
        removed+=len(old)-len(new); tr['items']=new
    return removed


def apply_prompt(clip_id:str,prompt:str)->dict[str,Any]:
    text=(prompt or '').strip().lower()
    if not text: raise ValueError('prompt vazio')
    revisions.create_revision(clip_id,'Antes do Prompt-to-Edit')
    data=deepcopy(timeline.get_or_create_timeline(clip_id)); state=editor.get_or_create_edit_state(clip_id)
    actions=[]
    if any(x in text for x in ('sem emoji','tirar emoji','remover emoji','sem emojis')):
        cues=editor.list_caption_cues(clip_id)
        for cue in cues: cue['emoji']=None
        editor.replace_caption_cues(clip_id,cues); actions.append('emojis removidos')
    if any(x in text for x in ('sem b-roll','tirar b-roll','remover b-roll','menos b-roll')):
        n=_remove_generated(data,{'broll'}); actions.append(f'{n} B-roll removidos')
    if any(x in text for x in ('sem efeito sonoro','sem sfx','tirar sfx','remover sfx')):
        n=_remove_generated(data,{'sfx'}); actions.append(f'{n} SFX removidos')
    if any(x in text for x in ('sem zoom','tirar zoom','remover zoom')):
        tr=timeline.track(data,'effects'); old=tr.get('items') or []; tr['items']=[x for x in old if 'zoom' not in str(x.get('effectId') or '').lower() and str((x.get('config') or {}).get('type') or '').lower()!='zoom']; actions.append(f'{len(old)-len(tr["items"])} zooms removidos')
    if any(x in text for x in ('mais rápido','mais rapido','edição rápida','edicao rapida')):
        data.setdefault('metadata',{}).setdefault('promptEdit',{})['pace']='fast'; actions.append('ritmo marcado como rápido')
    if any(x in text for x in ('mais suave','menos agressiv','limpo','clean')):
        data.setdefault('metadata',{}).setdefault('promptEdit',{})['pace']='clean'; actions.append('ritmo marcado como clean')
    if any(x in text for x in ('normalizar áudio','normalizar audio','volume uniforme','loudness')):
        audio=dict(state.get('audio_config') or {}); audio['loudness_normalize']=True; state['audio_config']=audio; editor.save_edit_state(clip_id,state); actions.append('loudness normalizado para social')
    if any(x in text for x in ('não normalizar áudio','nao normalizar audio','desativar loudness')):
        audio=dict(state.get('audio_config') or {}); audio['loudness_normalize']=False; state['audio_config']=audio; editor.save_edit_state(clip_id,state); actions.append('normalização de loudness desativada')
    m=re.search(r'legenda[s]?\s+(?:na cor\s+)?(branca|branco|amarela|amarelo|verde|vermelha|vermelho|azul)',text)
    if m:
        colors={'branca':'#FFFFFF','branco':'#FFFFFF','amarela':'#FFD400','amarelo':'#FFD400','verde':'#22C55E','vermelha':'#EF4444','vermelho':'#EF4444','azul':'#3B82F6'}
        cfg=dict(state.get('caption_config') or {}); cfg['color']=colors[m.group(1)]; state['caption_config']=cfg; editor.save_edit_state(clip_id,state); actions.append(f'cor da legenda → {m.group(1)}')
    if not actions:
        raise ValueError('Esse comando ainda não possui uma operação determinística segura. Use comandos como “sem zoom”, “remover B-roll”, “sem emojis” ou “legenda amarela”.')
    data.setdefault('metadata',{})['lastPromptEdit']={"prompt":prompt,"actions":actions}; timeline.save_timeline(clip_id,data)
    return {"ok":True,"actions":actions,"timeline":data}
