"""Read-only audit of snapshot functions; only synthetic local state/SQLite."""
from __future__ import annotations
import ast, asyncio, importlib.util, json, sys, types
from pathlib import Path
from sqlalchemy import Integer, String, select, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
ROOT=Path('/tmp/nexus-performance-reaudit2-2026-09-14/backend')
def extract(path,names,env):
 tree=ast.parse((ROOT/path).read_text())
 nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in names]
 module=ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0)]+nodes,type_ignores=[])
 exec(compile(ast.fix_missing_locations(module),str(ROOT/path),'exec'),env)
ns={};extract('app/core/database.py',{'release_idle_connection'},ns);release=ns['release_idle_connection']
mod=types.ModuleType('app.core.database');mod.release_idle_connection=release;sys.modules['app.core.database']=mod
spec=importlib.util.spec_from_file_location('audited_cache',ROOT/'app/core/cache.py');cache=importlib.util.module_from_spec(spec);spec.loader.exec_module(cache)
class Base(DeclarativeBase):pass
class Witness(Base):
 __tablename__='witness';id:Mapped[int]=mapped_column(Integer,primary_key=True);name:Mapped[str]=mapped_column(String)
async def main():
 results={};hold=asyncio.Event();entered=asyncio.Event();committing=asyncio.Event()
 class SlowSession:
  new=();dirty=();deleted=()
  def in_transaction(self):return True
  async def commit(self):committing.set();await asyncio.Event().wait()
 async def owner():
  async with cache.cache_single_flight('audit-cancel'):
   entered.set();await hold.wait()
 async def waiter():
  async with cache.cache_single_flight('audit-cancel',db=SlowSession()):pass
 a=asyncio.create_task(owner());await entered.wait();b=asyncio.create_task(waiter());await committing.wait();b.cancel();await asyncio.gather(b,return_exceptions=True);hold.set();await a
 results['cancel_during_release']={'locks_remaining':len(cache._inflight),'refs_remaining':dict(cache._inflight_refs)}
 async with cache.cache_single_flight('audit-cancel'):pass
 results['cancel_during_release']['refs_after_next_success']=dict(cache._inflight_refs)
 eng=create_async_engine('sqlite+aiosqlite:///:memory:')
 async with eng.begin() as conn:await conn.run_sync(Base.metadata.create_all)
 sessions=async_sessionmaker(eng,expire_on_commit=False,autoflush=False)
 async with sessions() as db:
  db.add(Witness(name='synthetic'));await db.flush();before={'new':len(db.new),'dirty':len(db.dirty),'deleted':len(db.deleted)}
  committed=await release(db);await db.rollback()
 async with sessions() as db:count=await db.scalar(select(func.count()).select_from(Witness))
 results['already_flushed_write']={'state_before':before,'helper_committed':committed,'rows_after_caller_rollback':count}
 async with sessions() as db:
  await db.execute(select(1));freed=await release(db);results['clean_read_release']={'released':freed,'transaction_after':db.in_transaction()}
 await eng.dispose()
 class HttpError(Exception):
  def __init__(self,status_code,detail):self.status_code=status_code;self.detail=detail
 env={'settings':types.SimpleNamespace(MAX_UPLOAD_SIZE_MB=1),'HTTPException':HttpError}
 extract('app/api/candidates.py',{'_read_upload_bounded','_validate_upload_size'},env)
 class Upload:
  def __init__(self,size):self.size=size;self.reads=[]
  async def read(self,n=-1):self.reads.append(n);return b'x'*min(self.size,n if n>=0 else self.size)
 u=Upload(3*1024*1024)
 try:await env['_read_upload_bounded'](u,label='audit')
 except HttpError as e:results['bounded_read']={'status':e.status_code,'read_sizes':u.reads,'total_upload_bytes':u.size}
 Path('/tmp/nexus-reaudit2-evidence-2026-09-14/backend-repro-results.json').write_text(json.dumps(results,indent=2)+'\n');print(json.dumps(results,indent=2))
asyncio.run(main())
