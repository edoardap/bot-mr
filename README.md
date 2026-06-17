# 🤖 GitLab Merge Request Discord Bot

Este bot integra o GitLab com o Discord, enviando resumos periódicos sobre o status dos **Merge Requests (MRs)** abertos de um grupo ou projeto específico no GitLab. Ele ajuda a equipe a acompanhar MRs pendentes, inativos e a carga de trabalho dos revisores.

---

## 🚀 Funcionalidades

* **📋 Aguardando Revisão:** Lista MRs que precisam de revisão e menciona os revisores responsáveis.
* **🛠️ Alterações Solicitadas:** Mostra MRs que possuem o label de alterações solicitadas para alertar os autores.
* **❓ Sem Revisor:** Identifica MRs que foram abertos mas ainda não possuem nenhum revisor atribuído.
* **⚖️ Carga de Trabalho:** Exibe a quantidade de MRs atribuídos a cada revisor.
* **⚠️ MRs Parados (Inativos):** Alerta sobre MRs sem atualizações há mais de $N$ dias.
* **👥 Mapeamento de Usuários:** Traduz o nome de usuário do GitLab em menções reais do Discord utilizando o arquivo `mapping.json`.
* **📄 Suporte a Listas Longas:** Caso haja muitos MRs abertos, o bot divide as mensagens automaticamente em múltiplos embeds limpos e contínuos para evitar erros de limites do Discord.

---

## ⚙️ Configuração (.env)

Copie o arquivo de exemplo para configurar suas credenciais:
```bash
cp app_build/.env.example app_build/.env
```

Configure as seguintes variáveis de ambiente no seu arquivo `.env`:

| Variável | Descrição |
|---|---|
| `DISCORD_TOKEN` | Token do bot do Discord criado no Discord Developer Portal. |
| `DISCORD_CHANNEL_ID` | ID do canal do Discord onde o bot enviará as mensagens. |
| `GITLAB_TOKEN` | Token de Acesso Pessoal (PAT) do GitLab com escopo `read_api`. |
| `GITLAB_URL` | URL da sua instância do GitLab (Ex: `https://gitlab.com` ou o GitLab interno da empresa). |
| `GITLAB_PROJECT_ID` | ID do projeto no GitLab (opcional se usar `GITLAB_GROUP_ID`). |
| `GITLAB_GROUP_ID` | ID do grupo no GitLab (caso queira monitorar múltiplos projetos dentro de um grupo). |
| `SUMMARY_INTERVAL_HOURS` | Intervalo em horas para postagem do resumo periódico (Ex: `24`). |
| `STALE_THRESHOLD_DAYS` | Dias de inatividade para considerar um MR como parado/stale (Ex: `3`). |

---

## 👥 Mapeamento de Usuários (`mapping.json`)

Para que o bot mencione os desenvolvedores no Discord em vez de apenas mostrar o nome de usuário do GitLab, edite o arquivo `app_build/mapping.json`:

```json
{
  "usuario_gitlab_1": "ID_DO_DISCORD_1",
  "usuario_gitlab_2": "ID_DO_DISCORD_2"
}
```

> **Dica:** Para pegar o ID do Discord de um usuário, ative o *Modo Desenvolvedor* nas configurações do seu Discord, clique com o botão direito no usuário e selecione **Copiar ID**.

---

## 💻 Como Executar Localmente

### Pré-requisitos
* Python 3.8 ou superior instalado.

### Passo a passo
1. Entre no diretório do aplicativo:
   ```bash
   cd app_build
   ```
2. Crie e ative um ambiente virtual:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```
3. Instale as dependências:
   ```bash
   pip install -r requirements.txt
   ```
4. Execute em modo de teste local (Dry-Run) para validar o formato:
   ```bash
   python bot.py --dry-run
   ```
5. Execute o bot de forma contínua:
   ```bash
   python bot.py
   ```

---

## 🐳 Como Executar com Docker (Recomendado para VPS / "Máquina X")

A conteinerização com Docker é a forma ideal para rodar o bot de maneira automatizada e persistente em um servidor dedicado.

### 1. Build da Imagem Docker
No diretório raiz do projeto (onde está o `.gitignore` e a pasta `app_build`), execute o comando para compilar a imagem:

```bash
docker build -t bot-mr ./app_build
```

### 2. Rodar o Container Localmente para Teste
```bash
docker run --env-file app_build/.env bot-mr
```

---

## 🛡️ Implantando na "Máquina X" (Servidor / VPS)

Para colocar o bot para rodar na máquina de destino definitiva, siga estas etapas:

### Passo 1: Transferir os arquivos
Envie a pasta do projeto para a **Máquina X** (via `git clone`, `scp` ou transferindo o zip).

### Passo 2: Criar o arquivo de ambiente na Máquina X
Crie um arquivo `.env` com as configurações reais de produção na Máquina X.

### Passo 3: Compilar a imagem Docker na Máquina X
Navegue até o diretório do projeto no servidor e execute:
```bash
docker build -t bot-mr ./app_build
```

### Passo 4: Executar o container em segundo plano (Detached Mode)
Inicie o container configurado para rodar permanentemente (24/7), reiniciando automaticamente caso o servidor caia ou o Docker reinicie:

```bash
docker run -d \
  --name bot-mr-prod \
  --env-file .env \
  --restart unless-stopped \
  bot-mr
```

### 📊 Gerenciando o Container no Servidor

* **Ver os logs em tempo real:**
  ```bash
  docker logs -f bot-mr-prod
  ```
* **Parar o bot:**
  ```bash
  docker stop bot-mr-prod
  ```
* **Iniciar o bot parado:**
  ```bash
  docker start bot-mr-prod
  ```
* **Verificar se está rodando:**
  ```bash
  docker ps
  ```
