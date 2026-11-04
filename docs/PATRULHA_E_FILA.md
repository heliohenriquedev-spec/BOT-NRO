# Patrulha e ordenação da fila

## Combate após portais e aproximação atrás de paredes

Portais de reposicionamento no mesmo mapa e transferências entre mapas preservam
a escolha de caça ligada/pausada. Comandos pendentes, bloqueios de movimento e IDs
de alvos antigos são descartados. A caça aguarda a conexão e a posição confirmada
do personagem no destino e passa a trabalhar com as aparições recebidas ali.
Não é possível continuar atacando um ID que deixou de existir na área de chegada.

Transferências clássicas 0092 têm IP/porta encaminhados por um novo listener do
relay, assim como a entrada inicial 0071. A remontagem respeita mensagens inteiras
e fragmentação TCP. Formatos desconhecidos são encaminhados sem alteração e com
diagnóstico, em vez de procurar bytes de opcode dentro de outras mensagens.
Uma desconexão sem transferência anunciada continua pausando a caça. Se a posição
de chegada não for confirmada em 20 segundos, a caça para com um motivo explícito.
Uma pausa manual nunca é desfeita pelo portal.

O afastamento de combate exige linha de visão: um monstro próximo em linha reta,
mas do outro lado da parede, não provoca fuga antes da aproximação. O caminho até
ele é mantido enquanto o jogador avança e continua válido. Mudança de alvo,
obstáculos, bloqueios ou deslocamento relevante do monstro invalidam esse caminho.
Buscas mais longas têm orçamento limitado; resultados sem rota aguardam brevemente
antes de outra busca, evitando recalcular o mesmo problema a cada atualização.

## Circuito do mapa

### Mapas estreitos e ramificados

Mapas com pouco chão largo são reconhecidos automaticamente como corredores.
Neles, a ordem segue cada ramificação em profundidade: avança até a ponta segura,
volta à bifurcação e continua pela próxima passagem. Pontas e curvas fechadas
recebem pontos de passagem obrigatórios dentro da margem de parede configurada.
Não é necessário cadastrar uma rota manual por mapa.

Esses pontos só contam como visitados ao passar a até duas células deles. Nos
corredores, pontos atrás de paredes não são marcados apenas por proximidade.
Áreas abertas continuam usando o circuito otimizado descrito abaixo; portais,
bloqueios e cobertura por ciclo continuam sendo respeitados.

Na simulação de yggdrasil01, três pontas antes ficavam a 11–14 células da trilha
apesar de o ciclo terminar. Com a visita por ramificações, as quatro pontas seguras
foram alcançadas a uma distância máxima de 1,4 célula. A simulação não inclui
perseguições de monstros ou correções de posição do servidor.

A patrulha prepara uma sequência de pontos de passagem usando as distâncias
caminháveis entre eles. Uma otimização limitada encurta cruzamentos e retornos
desnecessários antes de começar a percorrê-los. Pontos já cobertos são pulados,
e o avanço é mantido por mapa até o próximo ciclo.

A escolha do destino busca chão ainda não explorado; o caminho até ele não
recebe uma segunda penalidade por já ter sido percorrido. Isso evita desvios
para contornar a própria trilha. Paredes, portais e limites de segurança continuam
valendo. Becos e passagens únicas podem exigir voltar pelo mesmo trecho.

Na simulação de ve_fild04, partindo do mesmo ponto e com os mesmos parâmetros,
um ciclo passou de 3.097 para 2.664 células percorridas (aproximadamente 14% a
menos). O teste simula movimentos confirmados sem combate; o trajeto real pode
mudar com perseguições, obstáculos e correções do servidor.

## Arrastar quests

Na aba Fila de rotas, arraste uma rota para a posição desejada. Para mover um
grupo, use Ctrl+clique nas rotas ou Shift+clique para selecionar um intervalo e
arraste a seleção. A ordem é salva automaticamente, mantendo os itens marcados
ou desmarcados. Subir e Descer também movimentam a seleção múltipla.

A fila precisa estar pausada para editar. Selecionar uma linha não equivale a
marcar sua caixa: a seleção define o que mover; a caixa define o que executar.

## Investigação de GM em @hide — nenhuma detecção nova implementada

O código atual acompanha opções de invisibilidade recebidas, última posição
conhecida e sinais locais como fala, emoticon ou mudança de direção de um ator
não visível. Isso pode indicar um personagem oculto, mas não confirma cargo de
GM nem posição atual quando o servidor deixa de informá-la.

Na implementação pública de referência do rAthena, @hide ativa OPTION_INVISIBLE
e JT_INVISIBLE. A rotina de movimento não notifica objetos GM-hidden, e mudanças
de aparência invisível podem ser enviadas apenas ao próprio personagem:

- https://github.com/rathena/rathena/blob/master/src/map/atcommand.cpp
- https://github.com/rathena/rathena/blob/master/src/map/clif.cpp

Não temos o código nem uma captura controlada de um GM do NRO para provar quais
exceções esse servidor usa. Se ele não envia presença ou posição, o cliente e o
bot não conseguem recuperar essa informação mudando a GRF. Confirmação garantida
exigiria uma fonte disponibilizada pelos administradores, como API ou eventos
do próprio servidor. Nenhuma sondagem, pacote adicional ou mudança no detector
foi implementada nesta revisão.
