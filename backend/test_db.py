import time
from database import engine
from sqlmodel import Session, text

t0=time.time()
with Session(engine) as s:
    s.exec(text('SELECT 1')).one()
print(f'DB Time: {time.time()-t0}')
