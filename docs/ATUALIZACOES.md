# Atualizações: cada publicação leva tudo

Toda vez que o botão **Publicar atualização** é usado, a versão publicada é **completa**:
quem atualiza recebe o bot inteiro e todos os dados compartilhados daquele momento, não só o
que mudou desde a versão anterior. Por isso um usuário pode ficar várias versões sem atualizar
e, ao atualizar, recebe tudo o que foi publicado nesse meio-tempo.

## O que vai em toda publicação

- **Código e recursos do bot**: todos os arquivos listados em `versao.json`. O atualizador baixa
  o pacote inteiro da versão mais recente (ZIP do GitHub), substitui todos esses arquivos e apaga
  os que a versão nova não tem mais. Não existe atualização "por diferença".
- **Dados compartilhados** (`data/compartilhado`), sempre o conjunto completo do PC do
  desenvolvedor:
  - quests da fila (`rotas_quests.json`), com as missões, os IDs e o mapa de caça de cada uma;
  - quadros e missões (`quadros_missoes.json`);
  - rotas de mapa (`rotas_mapas.json`) e portais, inclusive os internos;
  - para onde cada portal leva (`portais_destinos.json`) e os NPCs de cada mapa com nome (`npcs.json`);
  - o @voltar aprendido (`quest_extras.json`, só ele);
  - sinais de GM.
- **Base de monstros** (`data/monstros_base`): IDs, nomes por mapa, HP e sprites.
- **Todo o funcionamento do bot**, inclusive os ajustes visuais (monstro some na hora ao morrer,
  habilidade multi-hit mostrada como um golpe com o dano inteiro). Eles vêm ligados para todos;
  quem quiser desligar cria o arquivo vazio `perfis/sem_remocao_visual`.

A cópia dos usuários **não publica**: o botão de publicar só existe no PC do desenvolvedor (com
git, repositório de origem e a pasta `perfis/desenvolvedor`, que nunca vai nas atualizações).

## Como chega no PC de cada usuário

1. O atualizador baixa a versão mais recente e grava todos os arquivos.
2. Com o código recém-instalado, os dados compartilhados são mesclados aos do usuário
   (uma vez por publicação): o que veio publicado substitui a cópia anterior do mesmo item, o que
   o usuário criou continua, e as escolhas dele (rotas marcadas na fila, missões do dia,
   progresso, Switch, configurações de combate) não mudam. Antes, uma cópia vai para `backups/`.
3. Ao abrir o painel, a mesclagem é conferida de novo.
4. Se algo for recusado, o motivo aparece no painel (Diagnóstico e linha de aviso), nunca só num
   console invisível.

Como cada publicação é completa, pular versões não perde nada: a mesclagem compara com o que o
usuário já importou e aplica o conjunto atual inteiro.

## O que nunca é enviado: configuração é de cada PC e de cada personagem

Nenhuma configuração vai na atualização. Cada computador mantém a sua, **separada por personagem**
(`data/rede/personagens/<nome>.json`): caça e patrulha, combate (ataque básico, aproximação,
kite), habilidades e a ordem delas, buffs aprendidos, alvos da aba Monstros, PvP, pausas de
presença, identificação de GM e alimentação do homúnculo. Quando outro personagem entra, o painel carrega a configuração
dele; um personagem novo começa com a configuração atual.

Nunca vão: os logs (`logs/`), as cópias de segurança (`backups/`) e a pasta `perfis/`.

Também ficam só no PC: Switch de montaria e equipamentos, os números de caça das quests (raio de
limpeza, tempo de calma, tentativas), progresso da fila, missões concluídas no dia, registro de
jogadores, database de drops e logs.

## Por que outros usuários "perdiam" atualizações (corrigido em 2026-11-04)

Os dados compartilhados eram gravados com a quebra de linha do Windows (CRLF) e o
`manifesto.json` guardava o hash desses bytes. O GitHub entrega os arquivos com LF, então no PC
dos outros o hash não batia e **toda** importação era recusada como "arquivo alterado", em silêncio:
a fila de quests ficava vazia, publicação após publicação. Agora:

- a conferência ignora a diferença entre CRLF e LF (os manifestos antigos continuam aceitos);
- os arquivos compartilhados são gravados com LF;
- a mesclagem durante a atualização usa o código novo, não o que estava carregado na memória;
- qualquer recusa aparece no painel.

## Ao publicar

- Publique pelo botão do painel; ele prepara recursos, exporta a base de monstros e os dados
  compartilhados, roda os testes e só então envia.
- Depois de atualizar, o outro usuário deve **reabrir o painel**. A fila dele deve mostrar as
  mesmas rotas; se não mostrar, o motivo está escrito no Diagnóstico.

## Changelog e aviso no Discord

As novidades ficam em `CHANGELOG.md`, em tópicos, na seção **Próxima atualização**. Ao publicar:

1. A seção vira `## <versão> (<data>)` e vai junto na publicação (os usuários recebem o histórico).
2. Depois do envio ao GitHub, os tópicos são postados no canal de atualizações do Discord por um
   webhook. A URL fica só no PC do desenvolvedor, em `perfis/desenvolvedor/discord_webhook.txt`
   (perfis/ nunca é publicado). Sem esse arquivo, ou se o Discord falhar, a publicação continua e o
   registro do painel avisa.
3. Com tópicos pendentes, o campo de mensagem do painel pode ficar vazio.

## Confirmação antes de atualizar

**Atualizar agora** abre uma confirmação com contagem mínima de cinco segundos.
A opção de confirmar só fica disponível ao terminar a contagem; cancelar não baixa
nem reinicia nada. Mesmo após confirmar, a conexão precisa estar fechada.

As mudanças implementadas devem ser registradas em **Próxima atualização**, no
`CHANGELOG.md`, antes de finalizar cada pedido. O registro não é uma transcrição
automática da conversa. Ao publicar, os itens pendentes recebem a versão e seguem
para o webhook do Discord já configurado. Apenas preparar ou editar o changelog
não envia mensagens. O procedimento de manutenção está em `AGENTS.md`.

Veja também `docs/DATABASE_COMPARTILHADO.md`: os dados de jogo do database passam
a acompanhar as versões com importação aditiva e sem duplicar as coletas locais.
