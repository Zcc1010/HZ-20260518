from pathlib import Path


def test_pyproject_enables_markitdown_pdf_support():
    repo_root = Path(__file__).resolve().parents[1]
    pyproject = (repo_root / "pyproject.toml").read_text(encoding="utf-8")

    assert 'markitdown[pdf,docx,pptx,xlsx,xls]>=0.1.0' in pyproject


def test_pdf_reference_documents_cli_and_ocr_boundary():
    repo_root = Path(__file__).resolve().parents[1]
    pdf_ref = (
        repo_root / "skills/office-document-parser/references/pdf.md"
    ).read_text(encoding="utf-8")

    assert 'markitdown "/path/to/file.pdf"' in pdf_ref
    assert "外部 OCR" in pdf_ref
    assert "/tmp/" not in pdf_ref
    assert "只有在用户明确要求处理后的文件或附件时" in pdf_ref
