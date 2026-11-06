# Database compartilhado

As atualizações passam a incluir `data/compartilhado/database.json`, produzido a
partir de uma leitura consistente do SQLite do desenvolvedor, inclusive os dados
já confirmados no arquivo WAL. São distribuídas as tabelas de informações de
monstros, drops informados pelo servidor, mortes observadas, itens observados e
associações de drops, mantendo os estados de candidato, revisado e rejeitado.
Os nomes, mapas, atributos e sprites dos monstros continuam sendo enviados pela
base de monstros já existente; o catálogo de itens acompanha os recursos da versão.

A publicação prepara esse conteúdo automaticamente. Ao instalar/atualizar, ou
abrir o painel após receber uma versão nova, o importador mescla os dados na base
local. Não é necessário copiar SQLite, WAL ou SHM manualmente.

O importador:

- preserva as observações que o jogador coletou;
- remapeia IDs locais para não misturar associações de bancos diferentes;
- registra a origem para não duplicar linhas ao reaplicar uma versão;
- preserva revisões locais e informações de servidor mais recentes;
- faz backup SQLite consistente em `backups/database_*.sqlite3`;
- importa em transação: uma associação inválida reverte a importação;
- mantém as associações candidatas como candidatas, sem declará-las comprovadas.

A exportação usa uma lista explícita de tabelas de jogo. Contas, senhas, preferências,
progresso de quests e tabelas desconhecidas não entram nesse snapshot. O arquivo
local `data/database/origem.json` identifica a origem das observações e permanece
protegido, assim como o SQLite local.

Preparar o snapshot não publica uma versão nem envia mensagens ao Discord. A
entrega aos jogadores ocorre na próxima publicação/atualização do bot.
