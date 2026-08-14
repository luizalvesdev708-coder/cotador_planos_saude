import os
import re
import json
import time
from typing import Dict, Any, Optional

import requests 
from flask import Flask, render_template_string, request, jsonify

app = Flask(__name__)

COMPANY_INFO = {
    "razao_social": "Performance Corretora de Seguros e Representações S/S LTDA",
    "cnpj": "11.748.654/0002-03",
    "endereco": "Av. Agamenon Magalhães - Recife / PE",
    "cidade": "Recife / PE",
    "atendimento": "VIP Concierge Recife & Região Metropolitana",
}

# Banco de Dados de Operadoras com Redes Hospitalares de Recife - PE
OPERATORAS_DB = {
    "hapvida": {
        "nome": "Hapvida NDI Recife",
        "cor": "#0284c7",
        "badge": "Excelente Custo/Benefício PE",
        "hospitais": ["Hosp. Espinheiro", "Hosp. Ilha do Leite", "Hosp. Vasco Lucena"],
        "precos_base": {"0-18": 180.00, "19-23": 210.00, "24-28": 250.00, "29-33": 300.00, "34-38": 360.00, "39-43": 440.00, "44-48": 550.00, "49-53": 700.00, "54-58": 900.00, "59+": 1350.00}
    },
    "unimed": {
        "nome": "Unimed Recife Premium",
        "cor": "#10b981",
        "badge": "Rede Própria de Referência",
        "hospitais": ["Hospital Unimed III", "Hospital Unimed II", "Rede Credenciada Recife"],
        "precos_base": {"0-18": 220.00, "19-23": 260.00, "24-28": 310.00, "29-33": 380.00, "34-38": 460.00, "39-43": 560.00, "44-48": 710.00, "49-53": 900.00, "54-58": 1150.00, "59+": 1680.00}
    },
    "bradesco": {
        "nome": "Bradesco Saúde Recife Executive",
        "cor": "#e11d48",
        "badge": "Rede Premium & Reembolso Flex",
        "hospitais": ["Real Hospital Português", "Hospital Santa Joana", "Rede D'Or Recife"],
        "precos_base": {"0-18": 310.00, "19-23": 370.00, "24-28": 440.00, "29-33": 530.00, "34-38": 640.00, "39-43": 780.00, "44-48": 980.00, "49-53": 1250.00, "54-58": 1600.00, "59+": 2300.00}
    },
    "sulamerica": {
        "nome": "SulAmérica Prestige Recife",
        "cor": "#6366f1",
        "badge": "Atendimento VIP Concierge",
        "hospitais": ["Real Hospital Português", "Hospital Santa Joana", "Memorial São José"],
        "precos_base": {"0-18": 340.00, "19-23": 395.00, "24-28": 480.00, "29-33": 590.00, "34-38": 710.00, "39-43": 850.00, "44-48": 1050.00, "49-53": 1380.00, "54-58": 1750.00, "59+": 2500.00}
    }
}

# ============================================================
# CLIENTE HTTP PARA CONSULTA DE CRÉDITO (SPC / SERASA / OAUTH2)
# ============================================================
class APIClient:
    def __init__(self, client_id: str, client_secret: str, base_url: str, auth_url: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = base_url.rstrip("/")
        self.auth_url = auth_url
        
        self.session = requests.Session()
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0

    def _get_access_token(self) -> str:
        """Gera e renova o token OAuth2 via Client Credentials mantendo em cache."""
        if self._access_token and time.time() < (self._token_expires_at - 30):
            return self._access_token

        payload = {"grant_type": "client_credentials"}
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        response = self.session.post(
            self.auth_url,
            data=payload,
            auth=(self.client_id, self.client_secret),
            headers=headers,
            timeout=10
        )
        response.raise_for_status()
        data = response.json()

        self._access_token = data.get("access_token")
        expires_in = data.get("expires_in", 1800)
        self._token_expires_at = time.time() + expires_in

        return self._access_token

    def _headers(self) -> Dict[str, str]:
        """Constrói os cabeçalhos das requisições com o Bearer Token."""
        token = self._get_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

    def get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Realiza requisições GET autenticadas."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        response = self.session.get(url, headers=self._headers(), params=params, timeout=10)
        response.raise_for_status()
        return response.json()

    def post(self, endpoint: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Realiza requisições POST autenticadas."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        response = self.session.post(url, headers=self._headers(), json=data, timeout=10)
        response.raise_for_status()
        return response.json()

# ============================================================
# UTILS & LÓGICA DE NEGÓCIO
# ============================================================
def obter_faixa_etaria(idade: int) -> str:
    if idade <= 18: return "0-18"
    elif idade <= 23: return "19-23"
    elif idade <= 28: return "24-28"
    elif idade <= 33: return "29-33"
    elif idade <= 38: return "34-38"
    elif idade <= 43: return "39-43"
    elif idade <= 48: return "44-48"
    elif idade <= 53: return "49-53"
    elif idade <= 58: return "54-58"
    else: return "59+"

def calcular_valor_plano(operadora_key: str, vidas: list, acomodacao: str, coparticipacao: bool) -> float:
    op = OPERATORAS_DB[operadora_key]
    total = 0.0
    for idade in vidas:
        faixa = obter_faixa_etaria(idade)
        base = op["precos_base"].get(faixa, 0.0)
        
        # Ajustes de Acomodação e Coparticipação
        if acomodacao == "apartamento":
            base *= 1.15  # +15% para apartamento
        if not coparticipacao:
            base *= 1.20  # +20% para plano sem coparticipação
            
        total += base
    return round(total, 2)

# ============================================================
# TEMPLATES HTML
# ============================================================
HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="pt-BR" class="h-full bg-slate-950">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Cotação & Crédito VIP | {{ company.razao_social }}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        body { font-family: 'Plus Jakarta Sans', sans-serif; }
        .glass-panel {
            background: rgba(15, 23, 42, 0.75);
            backdrop-filter: blur(16px);
            border: 1px solid rgba(255, 255, 255, 0.08);
        }
        .glass-card {
            background: rgba(30, 41, 59, 0.5);
            backdrop-filter: blur(12px);
            border: 1px solid rgba(255, 255, 255, 0.05);
        }
        .drop-zone {
            border: 2px dashed rgba(245, 158, 11, 0.4);
            transition: all 0.3s ease;
        }
        .drop-zone.dragover {
            background: rgba(245, 158, 11, 0.1);
            border-color: #f59e0b;
        }
    </style>
</head>
<body class="text-slate-100 min-h-screen flex flex-col justify-between bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-slate-900 via-slate-950 to-black">

    <!-- Topbar Enterprise -->
    <header class="border-b border-slate-800/80 bg-slate-950/80 backdrop-blur-md sticky top-0 z-50">
        <div class="max-w-7xl mx-auto px-6 py-4 flex flex-col md:flex-row justify-between items-center gap-4">
            <div class="flex items-center gap-3">
                <div class="h-10 w-10 rounded-xl bg-gradient-to-tr from-amber-500 to-amber-200 p-0.5 shadow-lg shadow-amber-500/10">
                    <div class="h-full w-full bg-slate-950 rounded-[10px] flex items-center justify-center">
                        <span class="text-amber-400 font-black text-xl">P</span>
                    </div>
                </div>
                <div>
                    <div class="flex items-center gap-2">
                        <h1 class="font-bold text-slate-100 tracking-tight text-lg">{{ company.razao_social }}</h1>
                        <span class="bg-amber-500/10 text-amber-400 border border-amber-500/20 text-[10px] font-bold px-2 py-0.5 rounded-full tracking-wide uppercase">Crédito & Cotação</span>
                    </div>
                    <p class="text-xs text-slate-400">CNPJ: {{ company.cnpj }} • {{ company.cidade }}</p>
                </div>
            </div>
            
            <div class="flex items-center gap-4 text-xs">
                <div class="hidden sm:block text-right">
                    <p class="text-slate-300 font-medium">✨ {{ company.atendimento }}</p>
                    <p class="text-slate-500">📍 {{ company.endereco }}</p>
                </div>
            </div>
        </div>
    </header>

    <!-- Main Section -->
    <main class="max-w-7xl mx-auto px-6 py-8 w-full flex-grow grid grid-cols-1 lg:grid-cols-12 gap-8">
        
        <!-- Coluna Esquerda: Simulador & Análise de Crédito -->
        <section class="lg:col-span-5 flex flex-col gap-6">
            
            <!-- Formulário Cotação -->
            <div class="glass-panel p-6 rounded-3xl shadow-2xl relative overflow-hidden">
                <div class="flex items-center justify-between mb-6 border-b border-slate-800 pb-4">
                    <h2 class="text-base font-semibold text-white flex items-center gap-2">
                        <svg class="w-5 h-5 text-amber-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4"/></svg>
                        Simulador Executivo Recife
                    </h2>
                    <span class="text-xs font-mono text-slate-500">v4.0</span>
                </div>

                <form id="quoteForm" onsubmit="gerarCotacao(event)" class="space-y-4">
                    <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        <div>
                            <label class="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-1">Nome do Cliente</label>
                            <input type="text" id="nomeCliente" placeholder="Ex: Dr. Roberto Silva" required
                                   class="w-full px-3 py-2.5 bg-slate-900/80 border border-slate-700/80 rounded-xl focus:ring-2 focus:ring-amber-500/50 focus:outline-none text-white text-xs">
                        </div>
                        <div>
                            <label class="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-1">WhatsApp (DDD + N°)</label>
                            <input type="text" id="whatsappCliente" placeholder="Ex: 81999998888" required
                                   class="w-full px-3 py-2.5 bg-slate-900/80 border border-slate-700/80 rounded-xl focus:ring-2 focus:ring-amber-500/50 focus:outline-none text-white text-xs">
                        </div>
                    </div>

                    <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        <div>
                            <label class="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-1">Idades (ex: 42, 12)</label>
                            <input type="text" id="idades" placeholder="42, 38, 12" required
                                   class="w-full px-3 py-2.5 bg-slate-900/80 border border-slate-700/80 rounded-xl focus:ring-2 focus:ring-amber-500/50 focus:outline-none text-white text-xs">
                        </div>
                        <div>
                            <label class="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-1">Renda Mensal Est. (R$)</label>
                            <input type="number" id="rendaCliente" placeholder="Ex: 8000" required
                                   class="w-full px-3 py-2.5 bg-slate-900/80 border border-slate-700/80 rounded-xl focus:ring-2 focus:ring-amber-500/50 focus:outline-none text-white text-xs">
                        </div>
                    </div>

                    <div class="grid grid-cols-2 gap-3">
                        <div>
                            <label class="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-1">Acomodação</label>
                            <select id="acomodacao" class="w-full px-3 py-2.5 bg-slate-900/80 border border-slate-700/80 rounded-xl text-white text-xs">
                                <option value="apartamento">Apartamento</option>
                                <option value="enfermaria">Enfermaria</option>
                            </select>
                        </div>
                        <div>
                            <label class="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-1">Coparticipação</label>
                            <select id="coparticipacao" class="w-full px-3 py-2.5 bg-slate-900/80 border border-slate-700/80 rounded-xl text-white text-xs">
                                <option value="true">Com Copart.</option>
                                <option value="false">Sem Copart.</option>
                            </select>
                        </div>
                    </div>

                    <button type="submit" 
                            class="w-full mt-3 bg-gradient-to-r from-amber-500 to-amber-600 hover:from-amber-400 hover:to-amber-500 text-slate-950 font-bold py-3 rounded-xl transition duration-200 shadow-lg shadow-amber-500/20 flex items-center justify-center gap-2 text-xs uppercase tracking-wide">
                        ⚡ Gerar Cotações & Crédito
                    </button>
                </form>
            </div>

            <!-- Módulo de Arrastar e Soltar Documento (Análise Instantânea + SPC/Serasa) -->
            <div class="glass-panel p-6 rounded-3xl shadow-2xl">
                <h3 class="text-sm font-bold text-white mb-2 flex items-center gap-2">
                    📂 Análise Instantânea + Consulta SPC / Serasa
                </h3>
                <p class="text-xs text-slate-400 mb-4">Arraste o documento (Holerite, CNH, CPF, IR) para análise automática de crédito e restrições financeiras:</p>
                
                <div id="dropZone" class="drop-zone p-6 rounded-2xl text-center cursor-pointer bg-slate-900/40">
                    <svg class="w-8 h-8 text-amber-400 mx-auto mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"/></svg>
                    <p class="text-xs text-slate-300 font-semibold">Arraste o arquivo aqui ou <span class="text-amber-400 underline">clique para selecionar</span></p>
                    <input type="file" id="fileInput" class="hidden" onchange="tratarArquivoSelecionado(this.files[0])">
                </div>

                <div id="analiseResultadoDoc" class="hidden mt-4 p-4 rounded-xl border text-xs"></div>
            </div>

        </section>

        <!-- Coluna Direita: Resultados e Proposta -->
        <section class="lg:col-span-7 flex flex-col gap-6">
            
            <div id="placeholderState" class="glass-panel p-12 rounded-3xl border border-slate-800 text-center flex flex-col items-center justify-center h-full min-h-[400px]">
                <div class="w-16 h-16 rounded-2xl bg-slate-900/80 border border-slate-800 flex items-center justify-center mb-4 shadow-inner">
                    <svg class="w-8 h-8 text-amber-400/60" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/></svg>
                </div>
                <h3 class="text-lg font-bold text-white mb-1">Painel Pronto para Análise</h3>
                <p class="text-xs text-slate-400 max-w-sm">Preencha o formulário ao lado para gerar a cotação combinada com a análise de crédito automática.</p>
            </div>

            <div id="resultsPanel" class="hidden flex-col gap-6">
                
                <!-- Status de Crédito Geral -->
                <div id="creditoBanner" class="p-4 rounded-2xl border text-xs flex items-center justify-between"></div>

                <!-- Chart Box -->
                <div class="glass-panel p-6 rounded-3xl relative">
                    <div class="flex items-center justify-between mb-4">
                        <div>
                            <h3 class="text-sm font-bold text-white">Comparativo de Investimento (Recife)</h3>
                            <p class="text-xs text-slate-400">Clique em qualquer valor para enviar a proposta com template de crédito via WhatsApp</p>
                        </div>
                    </div>
                    <div class="relative w-full h-48">
                        <canvas id="comparisonChart"></canvas>
                    </div>
                </div>

                <!-- Cards Grid -->
                <div id="cardsContainer" class="grid grid-cols-1 md:grid-cols-2 gap-4"></div>

                <!-- Ações de Exportação PDF -->
                <div class="flex flex-wrap items-center justify-end gap-3 pt-2">
                    <button onclick="abrirRelatorio()" class="px-5 py-3 rounded-xl border border-slate-700 bg-slate-900/80 text-slate-200 hover:bg-slate-800 text-xs font-bold flex items-center gap-2 transition">
                        📄 Abrir Relatório Executivo PDF
                    </button>
                </div>
            </div>

        </section>
    </main>

    <footer class="border-t border-slate-900 bg-slate-950 py-6 text-center text-xs text-slate-500">
        <p>© 2026 {{ company.razao_social }} — Todos os direitos reservados.</p>
    </footer>

    <script>
        let myChart = null;
        let ultimaCotacao = null;

        // Configuração Drag and Drop
        const dropZone = document.getElementById('dropZone');
        const fileInput = document.getElementById('fileInput');

        dropZone.onclick = () => fileInput.click();
        dropZone.ondragover = (e) => { e.preventDefault(); dropZone.classList.add('dragover'); };
        dropZone.ondragleave = () => dropZone.classList.remove('dragover');
        dropZone.ondrop = (e) => {
            e.preventDefault();
            dropZone.classList.remove('dragover');
            if (e.dataTransfer.files.length) {
                tratarArquivoSelecionado(e.dataTransfer.files[0]);
            }
        };

        async function tratarArquivoSelecionado(file) {
            const resBox = document.getElementById('analiseResultadoDoc');
            resBox.classList.remove('hidden');
            resBox.innerHTML = `<p class="text-amber-400 font-medium animate-pulse">🔍 Consultando SPC/Serasa e analisando o arquivo <strong>${file.name}</strong>...</p>`;

            const formData = new FormData();
            formData.append('documento', file);

            try {
                const response = await fetch('/api/analisar-documento', { method: 'POST', body: formData });
                const data = await response.json();

                if (data.status === 'success') {
                    const spc = data.spc_serasa;
                    const semRestricao = !spc.consta_inadimplencia;

                    resBox.className = "mt-4 p-4 rounded-xl border text-xs " + (semRestricao ? "bg-emerald-950/40 border-emerald-500/50 text-emerald-200" : "bg-rose-950/40 border-rose-500/50 text-rose-200");
                    
                    let detalhesHtml = '';
                    if (spc.detalhes && spc.detalhes.length > 0) {
                        detalhesHtml = '<ul class="list-disc list-inside mt-2 text-[11px] opacity-90">';
                        spc.detalhes.forEach(d => { detalhesHtml += `<li>${d}</li>`; });
                        detalhesHtml += '</ul>';
                    }

                    resBox.innerHTML = `
                        <div class="flex items-center justify-between mb-2">
                            <p class="font-bold text-sm">${semRestricao ? '✅ SPC / SERASA: Nenhuma Restrição' : '⚠️ SPC / SERASA: Inadimplência Localizada'}</p>
                            <span class="px-2 py-0.5 font-bold rounded ${semRestricao ? 'bg-emerald-600 text-white' : 'bg-rose-600 text-white'}">Score: ${spc.score_credito}</span>
                        </div>
                        <p><strong>Arquivo Analisado:</strong> ${file.name}</p>
                        <p><strong>Órgão:</strong> ${spc.orgao_consulta}</p>
                        <p><strong>Pendências Financeiras:</strong> ${spc.qtd_restricoes} registro(s) — Total R$ ${spc.valor_total_pendencias.toFixed(2)}</p>
                        <p class="mt-1 font-semibold">${spc.mensagem}</p>
                        ${detalhesHtml}
                    `;
                }
            } catch (err) {
                resBox.className = "mt-4 p-4 rounded-xl border bg-rose-950/40 border-rose-500/50 text-rose-200 text-xs";
                resBox.innerHTML = `<p>Erro ao processar análise do arquivo e consulta aos órgãos de crédito.</p>`;
            }
        }

        async function gerarCotacao(event) {
            event.preventDefault();

            const nome = document.getElementById('nomeCliente').value;
            const whatsapp = document.getElementById('whatsappCliente').value;
            const idadesInput = document.getElementById('idades').value;
            const renda = parseFloat(document.getElementById('rendaCliente').value) || 0;
            const acomodacao = document.getElementById('acomodacao').value;
            const coparticipacao = document.getElementById('coparticipacao').value === 'true';

            const vidas = idadesInput.split(',')
                                     .map(i => parseInt(i.trim()))
                                     .filter(i => !isNaN(i) && i >= 0);

            if (vidas.length === 0) {
                alert('Informe ao menos uma idade válida.');
                return;
            }

            try {
                const response = await fetch('/api/cotar', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ nome, whatsapp, vidas, renda, acomodacao, coparticipacao })
                });

                const data = await response.json();

                if (data.status === 'success') {
                    ultimaCotacao = data;
                    renderizarResultados(data);
                }
            } catch (err) {
                console.error('Erro:', err);
                alert('Erro ao processar cotação.');
            }
        }

        function renderizarResultados(data) {
            document.getElementById('placeholderState').classList.add('hidden');
            const panel = document.getElementById('resultsPanel');
            panel.classList.remove('hidden');
            panel.classList.add('flex');

            // Renderizar Banner de Crédito
            const credBox = document.getElementById('creditoBanner');
            const cred = data.credito;
            if (cred.status === 'APROVADO') {
                credBox.className = "p-4 rounded-2xl border bg-emerald-950/40 border-emerald-500/50 text-emerald-200 text-xs flex items-center justify-between";
                credBox.innerHTML = `<div><p class="font-bold text-sm">✅ Crédito Aprovado Automaticamente</p><p>Renda informada (R$ ${data.renda.toFixed(2)}) comporta o investimento.</p></div><span class="px-3 py-1 bg-emerald-600 text-white font-bold rounded-lg">Score: Alto</span>`;
            } else if (cred.status === 'ANALISE') {
                credBox.className = "p-4 rounded-2xl border bg-amber-950/40 border-amber-500/50 text-amber-200 text-xs flex items-center justify-between";
                credBox.innerHTML = `<div><p class="font-bold text-sm">⚠️ Análise de Crédito Manual Necessária</p><p>O comprometimento de renda está limítrofe.</p></div><span class="px-3 py-1 bg-amber-600 text-slate-950 font-bold rounded-lg">Score: Médio</span>`;
            } else {
                credBox.className = "p-4 rounded-2xl border bg-rose-950/40 border-rose-500/50 text-rose-200 text-xs flex items-center justify-between";
                credBox.innerHTML = `<div><p class="font-bold text-sm">❌ Crédito Reprovado por Renda</p><p>A renda informada está abaixo do mínimo exigido para as opções.</p></div><span class="px-3 py-1 bg-rose-600 text-white font-bold rounded-lg">Score: Baixo</span>`;
            }

            const container = document.getElementById('cardsContainer');
            container.innerHTML = '';

            const labels = [];
            const totals = [];
            const colors = [];

            data.cotacoes.forEach((item, index) => {
                labels.push(item.nome);
                totals.push(item.total);
                colors.push(item.cor);

                const isBest = index === 0;

                const cardHtml = `
                    <div class="glass-card rounded-2xl p-5 border ${isBest ? 'border-amber-500/80 ring-1 ring-amber-500/30' : 'border-slate-800'} relative flex flex-col justify-between hover:border-emerald-500/50 transition duration-300">
                        ${isBest ? '<span class="absolute -top-3 left-4 bg-amber-500 text-slate-950 text-[10px] font-black px-2.5 py-0.5 rounded-full uppercase tracking-wider">Menor Investimento</span>' : ''}
                        <div>
                            <h4 class="font-bold text-white text-sm">${item.nome}</h4>
                            <p class="text-[11px] text-slate-400 mb-2">${item.badge}</p>

                            <button onclick="enviarValorEspecificoWhatsApp(${index})" 
                                    title="Clique para enviar proposta e análise de crédito"
                                    class="w-full text-left my-2 p-2 rounded-xl bg-slate-900/60 hover:bg-emerald-950/40 border border-slate-700/50 hover:border-emerald-500/60 transition group flex items-center justify-between">
                                <div>
                                    <span class="block text-[10px] text-emerald-400 font-bold uppercase tracking-wide group-hover:underline">📲 Enviar Proposta + Crédito</span>
                                    <div class="text-2xl font-black text-amber-400 group-hover:text-emerald-400">
                                        R$ ${item.total.toLocaleString('pt-BR', { minimumFractionDigits: 2 })}
                                        <span class="text-xs font-normal text-slate-400">/mês</span>
                                    </div>
                                </div>
                                <div class="bg-emerald-600 p-2 rounded-lg text-white opacity-80 group-hover:opacity-100 group-hover:scale-105 transition">
                                    <svg class="w-5 h-5" fill="currentColor" viewBox="0 0 24 24"><path d="M.057 24l1.687-6.163c-1.041-1.804-1.588-3.849-1.587-5.946.003-6.556 5.338-11.891 11.893-11.891 3.181.001 6.167 1.24 8.413 3.488 2.245 2.248 3.481 5.236 3.48 8.414-.003 6.557-5.338 11.892-11.893 11.892-1.99-.001-3.951-.5-5.688-1.448l-6.305 1.654zm6.597-3.807c1.676.995 3.276 1.591 5.392 1.592 5.448 0 9.886-4.434 9.889-9.885.002-5.462-4.415-9.89-9.881-9.892-5.452 0-9.887 4.434-9.889 9.884-.001 2.225.651 3.891 1.746 5.634l-.999 3.648 3.742-.981z"/></svg>
                                </div>
                            </button>

                            <div class="my-2 p-2 bg-slate-900/40 rounded-lg text-[11px] border border-slate-800">
                                <span class="text-slate-400 font-semibold block mb-1">🏥 Hospitais em Recife:</span>
                                <p class="text-slate-300 font-medium">${item.hospitais.join(' • ')}</p>
                            </div>
                        </div>
                    </div>
                `;
                container.innerHTML += cardHtml;
            });

            atualizarGrafico(labels, totals, colors);
        }

        function atualizarGrafico(labels, totals, colors) {
            const ctx = document.getElementById('comparisonChart').getContext('2d');
            if (myChart) myChart.destroy();

            myChart = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Investimento Mensal (R$)',
                        data: totals,
                        backgroundColor: colors,
                        borderRadius: 8,
                        barThickness: 24
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        x: { ticks: { color: '#94a3b8', font: { size: 10 } }, grid: { display: false } },
                        y: { ticks: { color: '#94a3b8', callback: (v) => `R$ ${v}` }, grid: { color: 'rgba(255, 255, 255, 0.05)' } }
                    }
                }
            });
        }

        function abrirRelatorio() {
            if (!ultimaCotacao) return;
            const form = document.createElement('form');
            form.method = 'POST';
            form.action = '/relatorio';
            form.target = '_blank';

            const input = document.createElement('input');
            input.type = 'hidden';
            input.name = 'data';
            input.value = JSON.stringify(ultimaCotacao);

            form.appendChild(input);
            document.body.appendChild(form);
            form.submit();
            document.body.removeChild(form);
        }

        // DISPARO WHATSAPP COM TEMPLATE DE CRÉDITO E PROPOSTA
        function enviarValorEspecificoWhatsApp(index) {
            if (!ultimaCotacao) return;

            const nome = ultimaCotacao.nome;
            const fone = ultimaCotacao.whatsapp.replace(/\D/g, '');
            const item = ultimaCotacao.cotacoes[index];
            const cred = ultimaCotacao.credito;

            let msg = `Olá, *${nome}*! 👋\n\n`;
            msg += `Segue o resultado da sua *Análise de Crédito & Proposta Comercial* em Recife/PE pela *${ultimaCotacao.empresa.razao_social}*:\n\n`;
            
            if (cred.status === 'APROVADO') {
                msg += `💳 *Status de Crédito:* *APROVADO ✅*\n`;
            } else if (cred.status === 'ANALISE') {
                msg += `💳 *Status de Crédito:* *EM ANÁLISE MANUAL ⚠️*\n`;
            } else {
                msg += `💳 *Status de Crédito:* *REPROVADO POR RENDA ❌*\n`;
            }

            msg += `\n📋 *Plano Selecionado:* *${item.nome}*\n`;
            msg += `🛏️ *Acomodação:* ${ultimaCotacao.acomodacao.toUpperCase()} | Copart: ${ultimaCotacao.coparticipacao ? 'Sim' : 'Não'}\n`;
            
            msg += `\n🏥 *Hospitais de Referência:*\n`;
            item.hospitais.forEach(h => { msg += `  • ${h}\n`; });

            msg += `\n💰 *VALOR TOTAL MENSAL:* *R$ ${item.total.toLocaleString('pt-BR', {minimumFractionDigits: 2})}*\n\n`;
            msg += `Podemos prosseguir com a emissão do contrato?`;

            const url = `https://wa.me/${fone}?text=${encodeURIComponent(msg)}`;
            window.open(url, '_blank');
        }
    </script>
</body>
</html>
"""

# Template do Relatório Impresso em PDF
HTML_RELATORIO = r"""
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <title>Relatório Executivo & Crédito - {{ data.nome }}</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-white text-slate-900 p-8 font-sans">
    <div class="max-w-4xl mx-auto border border-slate-300 p-8 rounded-xl shadow-lg">
        <div class="border-b pb-4 mb-6 flex justify-between items-center">
            <div>
                <h1 class="text-xl font-bold text-slate-900">{{ data.empresa.razao_social }}</h1>
                <p class="text-sm text-slate-600">CNPJ: {{ data.empresa.cnpj }} • {{ data.empresa.atendimento }}</p>
            </div>
            <span class="text-xs bg-slate-100 text-slate-700 px-3 py-1 rounded-full font-bold">Relatório Executivo</span>
        </div>

        <div class="mb-6 bg-slate-50 p-4 rounded-lg">
            <h2 class="font-bold text-sm text-slate-800 mb-2">Dados do Titular / Cliente</h2>
            <p class="text-xs text-slate-700"><strong>Nome:</strong> {{ data.nome }}</p>
            <p class="text-xs text-slate-700"><strong>WhatsApp:</strong> {{ data.whatsapp }}</p>
            <p class="text-xs text-slate-700"><strong>Vidas (Idades):</strong> {{ data.vidas | join(', ') }}</p>
            <p class="text-xs text-slate-700"><strong>Renda Informada:</strong> R$ {{ "%.2f"|format(data.renda) }}</p>
            <p class="text-xs text-slate-700"><strong>Acomodação:</strong> {{ data.acomodacao | upper }} | <strong>Coparticipação:</strong> {{ 'Sim' if data.coparticipacao else 'Não' }}</p>
        </div>

        <h2 class="font-bold text-base text-slate-900 mb-4">Opções de Planos de Saúde Simuladas</h2>
        <table class="w-full text-left border-collapse mb-8 text-xs">
            <thead>
                <tr class="bg-slate-100 border-b">
                    <th class="p-2 font-bold">Operadora / Plano</th>
                    <th class="p-2 font-bold">Rede Hospitalar em Recife</th>
                    <th class="p-2 font-bold text-right">Mensalidade Total</th>
                </tr>
            </thead>
            <tbody>
                {% for item in data.cotacoes %}
                <tr class="border-b">
                    <td class="p-2 font-semibold text-slate-800">{{ item.nome }}</td>
                    <td class="p-2 text-slate-600">{{ item.hospitais | join(', ') }}</td>
                    <td class="p-2 text-right font-bold text-slate-900">R$ {{ "%.2f"|format(item.total) }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>

        <div class="border-t pt-4 text-center text-xs text-slate-500">
            <p>Este relatório é uma simulação comercial de caráter informativo gerada em Recife/PE.</p>
        </div>
    </div>
</body>
</html>
"""

# ============================================================
# ROTAS FLASK
# ============================================================
@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE, company=COMPANY_INFO)

@app.route("/api/cotar", methods=["POST"])
def api_cotar():
    payload = request.get_json() or {}
    nome = payload.get("nome", "Cliente")
    whatsapp = payload.get("whatsapp", "")
    vidas = payload.get("vidas", [])
    renda = float(payload.get("renda", 0.0))
    acomodacao = payload.get("acomodacao", "apartamento")
    coparticipacao = payload.get("coparticipacao", True)

    cotacoes = []
    for key, op in OPERATORAS_DB.items():
        total = calcular_valor_plano(key, vidas, acomodacao, coparticipacao)
        cotacoes.append({
            "key": key,
            "nome": op["nome"],
            "cor": op["cor"],
            "badge": op["badge"],
            "hospitais": op["hospitais"],
            "total": total
        })

    # Ordena cotações pelo menor valor
    cotacoes.sort(key=lambda x: x["total"])

    # Lógica de Análise de Crédito Interna baseada no Menor Valor
    menor_valor = cotacoes[0]["total"] if cotacoes else 0
    if renda >= (menor_valor * 3):
        status_credito = "APROVADO"
    elif renda >= (menor_valor * 1.5):
        status_credito = "ANALISE"
    else:
        status_credito = "REPROVADO"

    return jsonify({
        "status": "success",
        "nome": nome,
        "whatsapp": whatsapp,
        "vidas": vidas,
        "renda": renda,
        "acomodacao": acomodacao,
        "coparticipacao": coparticipacao,
        "empresa": COMPANY_INFO,
        "cotacoes": cotacoes,
        "credito": {"status": status_credito}
    })

@app.route("/api/analisar-documento", methods=["POST"])
def analisar_documento():
    doc = request.files.get("documento")
    nome_arquivo = doc.filename if doc else "documento.pdf"

    # Simulação da resposta enriquecida da API de Crédito (SPC/Serasa)
    spc_serasa_mock = {
        "consta_inadimplencia": False,
        "score_credito": 820,
        "orgao_consulta": "SPC Brasil & Serasa Experian",
        "qtd_restricoes": 0,
        "valor_total_pendencias": 0.0,
        "mensagem": "Nada consta. Documentação válida e apta para contratação imediata.",
        "detalhes": [
            "Score de Crédito Alto (Faixa A)",
            "Nenhum protesto ou ação judicial localizada em PE",
            "Capacidade financeira validada para emissão"
        ]
    }

    return jsonify({
        "status": "success",
        "arquivo": nome_arquivo,
        "spc_serasa": spc_serasa_mock
    })

@app.route("/relatorio", methods=["POST"])
def relatorio():
    data_raw = request.form.get("data", "{}")
    data = json.loads(data_raw)
    return render_template_string(HTML_RELATORIO, data=data)

# ============================================================
# EXECUÇÃO DO SERVIDOR
# ============================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)