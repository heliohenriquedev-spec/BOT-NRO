# Compatibilidade entre computadores — 04/11/2026

## Independência das GRFs visuais

Na execução da caça e das quests, o relay usa `MapRepository(independent=True)`:
não abre GRFs nem DATA.INI para obter colisões. A prioridade operacional é o
map cache do servidor e, depois, `data/recursos/colisoes.json`. Mapas ausentes
produzem um diagnóstico pedindo atualização da base do bot; não são substituídos
silenciosamente por uma colisão de GRF visual.

A munição usa exclusivamente `data/recursos/municao.json`, com os IDs dos itens,
inventário e confirmação de equipamento do servidor. Renomear itens em uma GRF
visual não altera o combate. As correções de leitura de GRFs descritas abaixo
continuam disponíveis para ferramentas de extração do desenvolvedor.

Publicar preserva a base operacional existente. Atualizações de ícones continuam
separadas dessa base. Para atualizar intencionalmente colisões e catálogo após
uma mudança real do servidor, o desenvolvedor deve revisar a fonte e executar
`prepare(refresh_combat=True)` de `nrobot.release_assets`, testar e publicar.
Uma GRF visual nova, por si só, não justifica essa reconstrução.

A independência é dos recursos visuais: mudanças reais no protocolo, IDs de itens
ou geometria do servidor ainda exigem atualizar o bot. O executável do cliente
continua sendo validado para interpretar e enviar os pacotes corretamente.

## O que foi conferido

A caça lê aparições, coordenadas e remoções da conexão do servidor. A seleção usa
as espécies configuradas ou descobertas, o mapa e os filtros de nome. O combate
confere alcance, recursos, recarga, munição e confirmação do servidor antes de
prosseguir. As quests fornecem os alvos à mesma rotina de combate e adicionam
os percursos, conversas dos quadros e confirmação de mortes.

A GRF visual não fornece a lista de monstros vivos do mapa inteiro. Ela interfere
nos recursos locais usados pelo bot: colisão, aliases dos mapas e nomes de itens.
Dois jogadores com o mesmo DATA.INI podem ter arquivos diferentes, ausentes ou
ilegíveis. A pasta privada `Arquivos_grf` do desenvolvedor não é distribuída.

## Correções

- DATA.INI aceita UTF-8, UTF-16 e ANSI, preservando nomes de GRF com acentos.
  Arquivos listados e ausentes agora aparecem entre as GRFs ignoradas no diagnóstico.
- A identificação de Kunai/Shuriken consulta tabelas legíveis por prioridade e um
  catálogo portátil em `data/recursos/municao.json`. A tabela local tem precedência
  por ID, inclusive quando um item deixou de ser munição compatível. Equipamento
  ainda exige item do tipo munição recebido no inventário e confirmação do servidor.
- A descoberta automática aceita o tipo explícito de monstro recebido do servidor
  sem aguardar o nome solicitado pelo cliente. Tipos ambíguos continuam exigindo
  identificação; jogadores, invocações e entidades com dono continuam excluídos.
  Filtros que distinguem nomes de monstros com a mesma aparência continuam exigindo
  o nome real recebido, evitando atacar outro monstro da mesma espécie visual.
- A preparação usa a pasta de jogo salva no painel. Colisões e munição são
  preparadas mesmo sem o índice privado de sprites do desenvolvedor.

## Publicação das quests

O botão Publicar prepara os recursos, a base de monstros e `data/compartilhado`.
O pacote inclui as quests, missões, descrições, modelos de pegar/entregar,
percursos até os quadros, retornos gravados, rotas dos mapas, portais e extras
compartilháveis. Colisões e base de monstros seguem em seus diretórios distribuídos.

Antes do envio, a publicação verifica referências a missões e rotas de mapa.
Para quests habilitadas, verifica as conversas de pegar/entregar e a presença do
percurso até cada quadro. Também verifica se os mapas dos cadastros compartilhados
existem no pacote de colisões e se suas dimensões são válidas. Uma dependência
ausente impede a publicação com a indicação do que falta.

`manifesto.json` registra hashes dos arquivos compartilhados. No recebimento,
arquivos ausentes ou alterados impedem a importação; os dados pessoais são
preservados e recebem backup antes de uma mesclagem válida. A mesclagem preserva
as escolhas pessoais de fila, progresso, login e equipamentos de cada personagem.
Cadastros antigos sem manifesto continuam compatíveis.

Para distribuir uma quest nova: termine as gravações e cadastros, teste os
percursos no jogo e publique pelo painel. Os outros jogadores devem atualizar
e reabrir o painel. Não precisam copiar sua pasta privada de GRFs recuperadas.
Os arquivos do cliente do jogo (GRF/DATA.INI) não são sobrescritos pelo atualizador.

## Resultado e limite da investigação

Neste computador, todas as GRFs listadas existem e os mapas testados carregam.
Foram preparados 35 nomes de munição e colisões de 1.085 mapas; os cadastros
compartilhados atuais dependem de 15 mapas. As referências das oito quests atuais
e as conversas das missões utilizadas passaram na conferência.

Sem logs dos computadores afetados, não é possível atribuir a falha deles a uma
única causa. As falhas de portabilidade acima foram corrigidas e reproduzidas em
testes; isso não substitui um teste de caça no computador afetado. Se persistir,
colete o diagnóstico da conexão nova, incluindo pasta do jogo, GRFs ignoradas,
catálogo de munição, colisão e motivo de bloqueio da habilidade.
