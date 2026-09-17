"""Read-only operator labels; original numbers never overwrite current assignments."""
import re

def usb_mac(value):
    value=(value or '').upper()
    return value if re.fullmatch(r'(?:[0-9A-F]{2}:){5}[0-9A-F]{2}',value) else None

def describe(db, originals, mac):
    if not mac:
        return dict(title='DEVICE NOT IDENTIFIED', badge='Unknown', detail='MAC will be read before upload', known=False, tone='unknown')
    row=db.get(mac)
    original=originals.get(mac)
    current=row.get('cube_id') if row else None
    if db.protected(mac):
        return dict(title='REGISTRATION STATION',badge='Protected station',detail=f'{mac} · Flashing blocked',known=True,tone='protected')
    if current is not None:
        title=f'NEOCORE #{current:02d}';badge=f'#{current:02d}'
    elif original is not None:
        title=f'ORIGINAL #{original:02d}';badge=f'Original #{original:02d}'
    elif row:
        title='KNOWN DEVICE';badge='In database'
    else:
        title='NEW DEVICE';badge='Not in database'
    labels=[]
    if original is not None:labels.append(f'Original #{original:02d}')
    labels.append('Saved in database' if row else 'Not in database')
    if row and current is None:labels.append('No current number assigned')
    labels.append(mac)
    return dict(title=title,badge=badge,detail=' · '.join(labels),known=bool(row or original is not None),tone='original' if original is not None else 'known' if row else 'unknown')
