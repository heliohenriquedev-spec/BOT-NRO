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
  - @voltar e as opções gerais das quests (`quest_extras.json`, sem o Switch de cada personagem);
  - buffs aprendidos e sinais de GM;
  - alvos da aba Monstros (`alvos_monstros.json`).
- **Base de monstros** (`data/monstros_base`): IDs, nomes por mapa, HP e sprites.

## Como chega no PC de cada usuário

1. O atualizador baixa a versão mais recente e grava todos os arquivos.
2. Com o código recém-instalado, os dados compartilhados são mesclados aos do usuário
   (uma vez por publicação): o que veio publicado substitui a cópia anterior do mesmo item, o que
   o usuário criou continua, e as escolhas dele (rotas marcadas na fila, missões do dia,
   progresso, Switch, configurações de combate) não mudam. Antes, uma cópia vai para `backups/`.
3. Ao abrir o painel, a mesclagem é conferida de novo e os alvos da aba Monstros são somados aos
   do usuário.
4. Se algo for recusado, o motivo aparece no painel (Diagnóstico e linha de aviso), nunca só num
   console invisível.

Como cada publicação é completa, pular versões não perde nada: a mesclagem compara com o que o
usuário já importou e aplica o conjunto atual inteiro.

## O que nunca é enviado

Login e senha, configurações de combate e de patrulha (`painel_config.json`, exceto os alvos da
aba Monstros), Switch de montaria e equipamentos, progresso da fila, missões concluídas no dia,
registro de jogadores, database de drops e logs.

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
