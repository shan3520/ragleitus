from app.services.pii_masking import mask_pii
def test_mask_pii():
    assert mask_pii("Contact user@example.com for info") == "Contact [REDACTED_EMAIL] for info"
