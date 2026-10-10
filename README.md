# Mesa do Mestre — versão Desktop

Programa para Windows (janela própria, sem navegador) para mestres de RPG de mesa organizarem **campanhas, jogadores,
personagens, XP manual, notas privadas, sessões, NPCs, missões e inventário** — e prepararem mensagens de
**WhatsApp/SMS** para os jogadores.

É uma aplicação **nativa** (Python + Qt/PySide6), escrita do zero para desktop, que **compartilha o mesmo banco de
dados** da versão web ([`../MesaDoMestre`](../MesaDoMestre)). A versão web continua existindo como plano B (e é a
que funciona bem no celular): o que você cadastra em uma aparece na outra, com as mesmas contas e senhas.

## Começo rápido

Pré-requisito: **Python 3.12 ou superior** ([python.org](https://www.python.org/downloads/); marque *Add python.exe to
PATH*). Nada mais.

1. Dê dois cliques em **`iniciar.bat`**.
   - Na primeira vez ele cria o ambiente virtual e instala as dependências (alguns minutos, precisa de internet).
2. Entre com a mesma conta da versão web (ou crie uma em **Criar conta**; a primeira conta de um banco vazio vira
   administradora).

Para fechar, feche a janela. **Sair** (menu lateral) volta para a tela de login.

### Executável independente (opcional)

Para ter um `MesaDoMestre.exe` que abre sem precisar do Python instalado:

```bat
build_exe.bat
```

O programa fica em `dist\MesaDoMestre\MesaDoMestre.exe` (copie a pasta `MesaDoMestre` inteira para onde quiser).

## O banco de dados compartilhado

Os dois programas leem e gravam **o mesmo arquivo SQLite**. O desktop o procura, nesta ordem:

1. variável de ambiente `MESA_DB` (caminho do arquivo);
2. o arquivo escolhido em **Configurações → Trocar arquivo do banco** (ou no botão da tela de login);
3. o banco da versão web, na pasta irmã: `..\MesaDoMestre\local\dados\mesa.sqlite3`;
4. `dados\mesa.sqlite3` dentro desta pasta (criado automaticamente se não existir).

Pontos importantes:

- **Mesmas contas:** a senha e a palavra-chave usam os mesmos hashes (Argon2id) nas duas versões.
- **Mesmo esquema:** quem manda no esquema do banco é a versão web (migrations). O desktop confere a revisão do
  esquema ao abrir e **recusa** um banco de versão diferente, com instruções (abra a versão web uma vez para atualizar,
  ou atualize este programa). Se o arquivo ainda não existe, o desktop cria um banco idêntico ao do web e o marca com
  a revisão atual — a versão web o aceita sem nenhuma migração.
- **Uso simultâneo:** é seguro abrir os dois, mas evite editar o *mesmo registro* nos dois ao mesmo tempo (vale o
  último a salvar). Cada tela recarrega os dados quando você troca de aba ou salva.
- **Backup:** o menu *Backup* gera o mesmo `.zip` da versão web (pode restaurar de um no outro). Você também pode
  simplesmente copiar o arquivo `mesa.sqlite3` com os dois programas fechados.

## O que o programa faz

| Tela | O que você faz |
|---|---|
| **Painel** | visão da campanha atual: contadores, próxima sessão, XP do grupo, notas e acontecimentos |
| **Campanhas** | criar/editar/excluir, status, capa, jogadores participantes, definir a campanha atual |
| **Jogadores** | cadastro com contato e consentimento, status, histórico de participação |
| **Personagens** | ficha completa, retrato, campos personalizados, status, inventário/missões/relações ligados |
| **Experiência** | barra de XP 0–100%: ±5/±10, valor livre, definir, zerar, completar, novo ciclo, alteração coletiva, histórico |
| **Sessões** | diário com participantes/NPCs/missões, acontecimentos, linha do tempo |
| **Notas** | notas privadas com categoria, importante/arquivada, busca e filtros |
| **NPCs** | ficha, imagem, segredos, relações com personagens |
| **Missões** | objetivos (marcar/remover), status com histórico, NPC e personagens |
| **Inventário** | itens, categorias, quem possui e quantidades |
| **Mensagens** | texto automático (ficha/XP, inventário, próxima sessão, resumo, missões, livre); abre WhatsApp/SMS, copia, ou envia direto (Twilio, opcional) |
| **Backup** | exportar/restaurar os seus dados (.zip) |
| **Minha conta** | senha, palavra-chave de recuperação, pedido de liberação de imagens, excluir conta |
| **Administração** | (administradores) liberar/revogar o envio de imagens |
| **Configurações** | banco de dados em uso, Twilio e código do país |

Regras iguais às da versão web: isolamento total entre contas, imagens recodificadas em WEBP (até 800 px, cota de
3 MB por conta, só com liberação), mensagens só com dados públicos, bloqueio de 10 min após 5 senhas erradas,
recuperação de senha por palavra-chave (sem e-mail).

## Celular

Este programa é para o computador. No celular use a **versão web** (responsiva) apontando para o mesmo banco:
rode `local\iniciar.bat` do projeto web — o que for feito pelo celular aparece aqui e vice-versa.

## Desenvolvimento

```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest
```

Os testes usam bancos temporários (nunca tocam nos seus dados) e a interface em modo *offscreen*.

```
mesa_desktop/
  paths.py        onde ficam o banco e as preferências (%APPDATA%\MesaDoMestreDesktop\config.json)
  db.py           conexão SQLite compartilhada, verificação/criação do esquema
  models.py       modelos SQLAlchemy das MESMAS tabelas do app web
  services/       regras de negócio (auth, crud, xp, backup, mensagens, imagens) — sem nada de interface
  ui/             janela principal, telas (pages/), componentes (kit.py), tema (theme.py)
tests/            serviços, compatibilidade e interface
```

Se o esquema do app web mudar (nova migration), atualize `models.py` e `SCHEMA_REVISION` em `db.py`.
