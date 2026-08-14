import json
import pytest
from unittest.mock import patch, MagicMock
from app import app, obter_faixa_etaria, calcular_valor_plano, APIClient

# ============================================================
# FIXTURES
# ============================================================
@pytest.fixture
def client():
    """Fixture que fornece o cliente de testes do Flask."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client

# ============================================================
# 1. TESTES UNITÁRIOS: REGRAS DE NEGÓCIO DA COTAÇÃO
# ============================================================
class TestRegrasDeNegocio:

    @pytest.mark.parametrize("idade, faixa_esperada", [
        (0, "0-18"),
        (18, "0-18"),
        (19, "19-23"),
        (23, "19-23"),
        (24, "24-28"),
        (42, "39-43"),
        (58, "54-58"),
        (59, "59+"),
        (80, "59+"),
    ])
    def test_obter_faixa_etaria(self, idade, faixa_esperada):
        """Valida se o enquadramento de idades nas faixas etárias está correto."""
        assert obter_faixa_etaria(idade) == faixa_esperada

    def test_calcular_valor_plano_base(self):
        """Testa o cálculo sem taxas adicionais (Enfermaria + Com Coparticipação)."""
        vidas = [20, 30]  # Faixas: '19-23' (210) e '29-33' (300) no Hapvida
        valor = calcular_valor_plano("hapvida", vidas, acomodacao="enfermaria", coparticipacao=True)
        assert valor == 510.00

    def test_calcular_valor_plano_com_acrescimos(self):
        """Testa o cálculo aplicando adicionais de Apartamento (+15%) e Sem Coparticipação (+20%)."""
        vidas = [20]  # Hapvida '19-23' = R$ 210,00
        # R$ 210 * 1.15 (Apartamento) * 1.20 (Sem Copart) = 289.8
        valor = calcular_valor_plano("hapvida", vidas, acomodacao="apartamento", coparticipacao=False)
        assert valor == 289.80

# ============================================================
# 2. TESTES UNITÁRIOS: CLIENTE HTTP OAUTH2 (MOCKING)
# ============================================================
class TestAPIClient:

    @patch("requests.Session.post")
    def test_get_access_token_success(self, mock_post):
        """Testa a geração e renovação do token OAuth2 com Mock no requests."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "mock_token_12345",
            "expires_in": 3600
        }
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        client = APIClient(
            client_id="id_test",
            client_secret="secret_test",
            base_url="https://api.test.com",
            auth_url="https://api.test.com/oauth/token"
        )

        token = client._get_access_token()
        assert token == "mock_token_12345"
        assert client._access_token == "mock_token_12345"
        mock_post.assert_called_once()

# ============================================================
# 3. TESTES DE INTEGRAÇÃO: ENDPOINTS DA API FLASK
# ============================================================
class TestEndpointsAPI:

    def test_rota_index(self, client):
        """Garante que a página principal carrega corretamente (Status 200)."""
        response = client.get("/")
        assert response.status_code == 200
        assert b"Performance Corretora" in response.data

    def test_api_cotar_credito_aprovado(self, client):
        """Testa o endpoint /api/cotar quando a renda é suficiente para aprovar crédito."""
        payload = {
            "nome": "Luiz Fernando",
            "whatsapp": "81999999999",
            "vidas": [27],
            "renda": 10000.0,
            "acomodacao": "apartamento",
            "coparticipacao": True
        }
        response = client.post("/api/cotar", data=json.dumps(payload), content_type="application/json")
        data = response.get_json()

        assert response.status_code == 200
        assert data["status"] == "success"
        assert len(data["cotacoes"]) == 4  # Retorna as 4 operadoras
        assert data["credito"]["status"] == "APROVADO"
        # Garante que a lista de cotações veio ordenada do menor para o maior preço
        assert data["cotacoes"][0]["total"] <= data["cotacoes"][-1]["total"]

    def test_api_cotar_credito_reprovado(self, client):
        """Testa /api/cotar quando a renda é baixa demais."""
        payload = {
            "nome": "Cliente Teste",
            "whatsapp": "81988887777",
            "vidas": [50, 55],
            "renda": 500.0,
            "acomodacao": "apartamento",
            "coparticipacao": False
        }
        response = client.post("/api/cotar", data=json.dumps(payload), content_type="application/json")
        data = response.get_json()

        assert response.status_code == 200
        assert data["credito"]["status"] == "REPROVADO"

    def test_api_analisar_documento(self, client):
        """Testa a rota de upload e análise simulada de documento (SPC/Serasa)."""
        data = {
            "documento": (open(__file__, "rb"), "comprovante_renda.pdf")
        }
        response = client.post(
            "/api/analisar-documento",
            data=data,
            content_type="multipart/form-data"
        )
        res_json = response.get_json()

        assert response.status_code == 200
        assert res_json["status"] == "success"
        assert res_json["arquivo"] == "comprovante_renda.pdf"
        assert res_json["spc_serasa"]["score_credito"] == 820

    def test_rota_relatorio_pdf_html(self, client):
        """Testa o endpoint de geração do HTML do relatório executivo."""
        mock_data = {
            "nome": "Luiz",
            "whatsapp": "81999999999",
            "vidas": [27],
            "renda": 5000.0,
            "acomodacao": "apartamento",
            "coparticipacao": True,
            "empresa": {"razao_social": "Performance Corretora", "cnpj": "00.000.000/0001-00"},
            "cotacoes": [
                {"nome": "Hapvida", "hospitais": ["Hospital A"], "total": 250.0}
            ]
        }
        response = client.post("/relatorio", data={"data": json.dumps(mock_data)})

        assert response.status_code == 200
        assert b"Relatorio Executivo" in response.data
        assert b"Luiz" in response.data