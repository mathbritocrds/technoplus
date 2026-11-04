"""Runtime HTML context must not prevent normal static-file refreshes."""
import asyncio
from contextvars import ContextVar

from app.demo import ScopedStaticFiles


def test_html_changes_are_visible_without_restarting_the_server(tmp_path):
    index=tmp_path/'index.html'
    index.write_text('<html><head></head><body>First version<script src="/business.js"></script></body></html>')
    files=ScopedStaticFiles(directory=str(tmp_path),html=True,
        context=ContextVar('test_demo',default=True),base_path_context=ContextVar('test_base',default='/corp'))
    first=asyncio.run(files.get_response('index.html',{'type':'http','method':'GET','headers':[]}))
    assert 'First version' in first.body.decode()
    index.write_text('<html><head></head><body>Updated version<script src="/business.js"></script></body></html>')
    second=asyncio.run(files.get_response('index.html',{'type':'http','method':'GET','headers':[]}))
    rendered=second.body.decode()
    assert 'Updated version' in rendered and 'First version' not in rendered
    assert 'globalThis.SIGI_CONTEXT={"basePath":"/corp","demo":true}' in rendered
    assert 'src="/corp/business.js"' in rendered
    assert second.headers['cache-control']=='no-store'


def test_code_assets_require_revalidation_including_annual_and_accounting(tmp_path):
    for filename in ('business.js','accounting.bundle.js','accounting.css','service-worker.js'):
        (tmp_path/filename).write_text('first')
    files=ScopedStaticFiles(directory=str(tmp_path),html=True,
        context=ContextVar('asset_demo',default=True),base_path_context=ContextVar('asset_base',default='/demo'))
    for filename in ('business.js','accounting.bundle.js','accounting.css','service-worker.js'):
        response=asyncio.run(files.get_response(filename,{'type':'http','method':'GET','headers':[]}))
        assert response.status_code==200
        assert response.headers['cache-control']=='no-cache, must-revalidate'
