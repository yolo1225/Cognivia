from types import SimpleNamespace

from app.services.resource_export_service import _export_file_name, _safe_stem


def test_export_file_stem_preserves_resource_title_and_removes_illegal_characters() -> None:
    assert _safe_stem('RAG 入门：检索 / 生成?') == 'RAG 入门：检索 生成'
    assert _safe_stem(r'RAG\检索') == 'RAG 检索'


def test_export_file_stem_removes_windows_trailing_characters() -> None:
    assert _safe_stem('  学习资源. ') == '学习资源'


def test_export_file_name_uses_resource_title_version_and_audience() -> None:
    resource = SimpleNamespace(title='RAG 入门：检索 / 生成?', public_id='res_001', version=2)

    assert _export_file_name(resource, 'learner', '.docx') == 'RAG 入门：检索 生成_v2_学习者版.docx'
    assert _export_file_name(resource, 'teacher', '.docx') == 'RAG 入门：检索 生成_v2_教师版.docx'
