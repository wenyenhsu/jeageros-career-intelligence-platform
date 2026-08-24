import pytest
from django.urls import reverse
from pathlib import Path

from apps.applications.services.materials_pack_service import (
    MaterialsPackError,
    MaterialsPackService,
)


def _seed_templates(settings):
    root = Path(settings.RESUME_TEMPLATE_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    names = [
        "Cover_Letter_AI.pdf",
        "WenYenHsu_Resume_AI.pdf",
        "Cover_Letter_AI.docx",
        "WenYenHsu_Resume_AI.docx",
        "Cover_Letter_infra.docx",
        "WenYenHsu_Resume_infra.pdf",
        "WenYenHsu_Resume_infra.docx",
    ]
    for name in names:
        (root / name).write_text(f"template {name}", encoding="utf-8")
    return root


@pytest.mark.django_db
def test_application_list_shows_materials_pack_dropdown(client, application):
    response = client.get(reverse("application-list"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Materials" in content
    assert 'name="pack"' in content
    assert 'value="AI"' in content
    assert 'value="INFRA"' in content
    assert "Infra" in content
    assert "confirmMaterialsPack" in content
    assert "Apply this materials pack to the application folder?" in content


@pytest.mark.django_db
def test_copying_ai_pack_leaves_templates_in_place(
    application, application_materials_root, settings
):
    template_root = _seed_templates(settings)

    result = MaterialsPackService().apply_pack(application, "AI")

    dest = Path(application.materials_local_path)
    assert result["pack"] == "AI"
    assert result["missing"] == []
    for name in MaterialsPackService.PACK_FILES["AI"]:
        assert (dest / name).is_file()
        assert (template_root / name).is_file()
    application.refresh_from_db()
    assert application.materials_pack == "AI"


@pytest.mark.django_db
def test_copying_infra_pack_skips_missing_pdf(
    application, application_materials_root, settings
):
    _seed_templates(settings)

    result = MaterialsPackService().apply_pack(application, "Infra")

    dest = Path(application.materials_local_path)
    assert result["pack"] == "INFRA"
    assert "Cover_Letter_infra.pdf" in result["missing"]
    assert (dest / "WenYenHsu_Resume_infra.pdf").is_file()
    assert (dest / "Cover_Letter_infra.docx").is_file()
    assert not (dest / "Cover_Letter_infra.pdf").exists()


@pytest.mark.django_db
def test_materials_pack_view_copies_ai_files(
    client, application, application_materials_root, settings
):
    _seed_templates(settings)

    response = client.post(
        reverse("application-materials-pack", args=[application.pk]),
        data={"pack": "AI", "next": reverse("application-list")},
    )

    assert response.status_code == 302
    dest = Path(application.materials_local_path)
    assert (dest / "WenYenHsu_Resume_AI.pdf").read_text(encoding="utf-8") == (
        "template WenYenHsu_Resume_AI.pdf"
    )
    application.refresh_from_db()
    assert application.materials_pack == "AI"


@pytest.mark.django_db
def test_invalid_pack_raises(application):
    with pytest.raises(MaterialsPackError):
        MaterialsPackService().apply_pack(application, "")
