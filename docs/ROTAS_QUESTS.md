# Rota de quests

## Montar uma rota (fluxo atual)

1. **Mapas de caca**: grave uma vez o caminho ate cada mapa de caca. Posicione o
   personagem onde o bot vai partir (onde o Retorno te deixa), clique em **Gravar nova
   rota**, caminhe, entre nos portais e fale com os NPCs de transporte. No mapa de caca,
   espere parar e clique em **Salvar gravacao**. Grave tambem a volta (mapa de caca ate a
   cidade/hospital): rotas gravadas servem de ligacao para ir entregar.
2. **Fila de rotas → Nova quest**: informe o nome, escolha o **Mapa de caca** e marque as
   missoes. A lista mostra todas as missoes que os quadros oferecem (as cadastradas e
   todos os ranks vistos nos menus), com "✓ concluida hoje" nas diarias ja feitas.
   Nao ha monstros, quantidades nem mensagens para preencher.
3. **Executar fila marcada**: pega as missoes (pulando as concluidas hoje), vai ao mapa,
   caca ate todos os contadores fecharem e volta para entregar.

Monstros e quantidades vem de cada missao ("Monstros necessarios"). Se a missao ainda
nao tem descricao, o bot le os monstros no quadro na hora de pegar e guarda no cadastro.
Missoes puladas nao entram no contador nem na entrega.

A coleta e a entrega usam um modelo gravado uma vez ("Gravar como pegar" / "Gravar como
entregar") e valem para todas as missoes dos dois quadros. Nenhuma mensagem de sucesso
e usada: a coleta vale quando a missao aparece no slot e a entrega quando sai do slot.
Se o quadro responder "Voce precisa matar todos os monstros da lista", a fila para com
"ainda nao concluida (faltam monstros)".

Entre rotas: ao entregar as missoes de uma rota num quadro, o bot ja pega ali as missoes da
proxima rota desse quadro, antes de sair. Depois da ultima entrega, se todas as missoes da
proxima rota ja estao pegas e a viagem dela passa pela Sala Vip (Viajante Ninja), segue
direto, sem Retorno.

Ordem: primeiro as missoes de Kakashi, depois as da Sala Vip. Se a viagem ao mapa de caca
passa pela Sala Vip (Viajante Ninja em ra_in01), o bot segue dali sem usar o Retorno.

Os 8 slots sao os mesmos nos dois quadros e mostram so o rank ("Rank A-1"). O bot guarda
qual missao cadastrada esta em cada slot que ele preencheu (`data/rede/slots_missoes.json`),
para nao confundir a Rank A-1 de Kakashi com a Rank A-1 da Sala Vip, ao pegar e ao entregar.

Na viagem, o bot vai direto ao proximo portal ou NPC do mapa pelo caminho mais curto,
sem repetir cada clique gravado. Se for teleportado para outro ponto do mapa, segue do
ponto da gravacao mais proximo. Ao chegar no mapa de caca, a caca comeca ali. O caminho e
calculado uma vez e seguido enquanto o personagem estiver nele (antes era recalculado a
cada passo, o que travava o relay e o jogo depois de um teleporte para longe).

## Coleta por slots livres e missoes escolhidas na rota

Uma gravacao completa de **Gravar como pegar** que passa por "Aceitar uma missao",
slot vazio, rank e "Aceitar missao" ensina um **modelo do quadro**. O numero do
slot e o rank da demonstracao nao ficam fixos: o bot troca o rank pela missao
selecionada na rota e consulta as vagas atuais do quadro.

Para cada missao marcada, o bot reconhece se ela ja aparece em um slot ocupado;
caso contrario, escolhe um slot realmente vazio, seleciona o rank e confirma a
aceitacao. Depois reabre o quadro e confere a missao no slot escolhido. Repete
para todas as missoes da rota e somente depois retorna e segue para a caca.

Os dois quadros usam o mesmo roteiro: o modelo gravado em um vale tambem para o outro
(Kakashi usa o modelo da Sala Vip enquanto nao tiver o proprio), entao qualquer missao
cadastrada com rank pode ser pega sem gravacao propria. Entre missoes do mesmo quadro o
bot nao reabre o quadro so para conferir: o menu de slots da missao seguinte confirma a
anterior; a ultima e conferida antes do Retorno. Missao diaria ja feita (a descricao mostra
"Status : Completa" ou o quadro responde "Voce ja completou esta missao") e pulada sem
aceitar, e as demais continuam; o resultado lista as puladas. Se o quadro recusar por
outro motivo (slot continua vazio), a fila para e mostra a resposta do NPC. Paginas extras sao avancadas;
um "Sim/Nao" logo apos "Aceitar missao" e respondido com Sim; outro menu inesperado e
cancelado, sem escolher nada. O texto do NPC aparece no console como `[ROTA] NPC diz:`.

Em **Selecionar missoes das opcoes salvas**, as missoes ja cadastradas vem marcadas.
Marcar cadastra; desmarcar remove do cadastro (com confirmacao; as usadas em rotas sao
mantidas).

Sem vagas, a fila pausa e informa qual missao falta. Nenhuma missao existente e
abandonada para liberar espaco. Grave um exemplo completo por quadro; em fluxos
diferentes ou sem modelo reconhecido, e necessaria uma gravacao especifica.
A entrega tambem pode usar um modelo gravado de "Completar missao", localizando
o rank no slot atual. Ela exige resposta de sucesso e retirada da missao do menu.

Em **Fila de rotas**, use **Executar so coleta da rota** ou **Executar so entrega
da rota** para testar todas as missoes daquela etapa, incluindo o retorno, sem
iniciar combate ou a proxima rota. Para testar a coleta nao e preciso ter gravado
a entrega nem a viagem aos monstros.

## Alvos recuperados da gravacao

O campo "Monstros necessarios" do NPC e a fonte dos nomes e quantidades. "25
Verme" aparece como Verme mesmo se o sprite/ID ainda nao constar no catalogo.
Os registros antigos sao relidos; nao e preciso regravar descricoes ja presentes.
IDs sao associados por nome exato: Inseto Guardiao nao vira tambem Guardiao,
nem Pequena Tartaruga vira tambem Tartaruga. Sem correspondencia de ID, o nome
recebido permanece visivel e pode ser vinculado em **Configurar rank e monstros**.

Slots ocupados como "#2 Rank A-2" nao sao novos tipos de missao no catalogo. O
bot gerencia esses slots automaticamente; na rota voce marca os ranks desejados.

## Retorno apos pegar ou entregar

O fluxo dos quadros compartilhados agora e: pegar as missoes daquele quadro,
usar **Retorno**, viajar/cacar, entregar as missoes e usar **Retorno** novamente.
Missoes consecutivas do mesmo quadro sao resolvidas antes de sair; ao trocar de
quadro, o retorno tambem ocorre. Nenhuma etapa continua antes do teletransporte
ser confirmado pelo servidor e da posicao do personagem estar disponivel.

- Sala Vip: NPC **Retorno**, `ra_in01 [213,80]`.
- Kakashi: NPC **Retorno**, `kakashi [83,150]`.

Se o NPC teletransporta ao clicar, nao e necessario gravar um dialogo: o bot vai
ate ele, acessa-o e aguarda a mudanca real. O mapa de retorno nao e presumido como
hospital; usa-se o destino que o servidor informar. Caso Retorno abra menus ou
peca confirmacao, use **Gravar retorno do quadro**, caminhe/acione Retorno no jogo,
escolha suas opcoes e salve depois de chegar ao destino. **Executar Retorno** testa
esse trecho isoladamente. A gravacao fica compartilhada para todas as rotas.

Ao gravar Retorno, a mudanca de mapa confirma e encerra a captura desse trecho.
O NPC de origem e a posicao de chegada ficam preservados. Voce pode salvar depois
de retornar ao ponto, mesmo que o NPC ja nao esteja visivel. Fechamentos atrasados
do dialogo do mapa anterior nao invalidam o percurso confirmado.

As trocas de mapa tambem avancam as etapas quando o portal dispara antes da
ultima celula gravada. Pontos de caminhada dentro da margem do portal nao sao
mais tratados como destinos bloqueados independentes. Uma mudanca para mapa
diferente do proximo esperado continua sendo bloqueada, para nao pular trechos.

## Rank, descricoes e monstros por missao

Codigos de cor como `^FF0000` e `^000000` sao removidos da exibicao. O texto
original da opcao continua salvo para selecionar o item correto no jogo. Slots
vazios e botoes de navegacao nao aparecem como candidatos a missao.

Ao gravar menus/opcoes, abra o rank desejado para o NPC enviar sua descricao.
O bot associa essa resposta ao rank selecionado e procura nomes de monstros
conhecidos na descricao. Nao existe uma correspondencia presumida entre numero
de rank e monstro. Menus gravados antes dessa versao podem nao ter descricoes.

Use **Configurar rank e monstros** para informar/corrigir nome, rank, mapa,
descricao e alvos de cada missao. Nas listas e em **Editar rota**, aparecem o rank
e os nomes dos monstros; quando faltam dados, aparece "monstros nao informados".
Marque as missoes desejadas para aquela rota e use **Usar monstros das missoes
marcadas nesta rota** para copiar os IDs e, quando unico, o mapa configurado.
Missoes de mapas diferentes devem ficar em rotas de caca separadas.

## Cadastro compartilhado dos quadros (fluxo recomendado)

### Validar uma etapa sem iniciar a fila

Na tela **Quadros e missoes compartilhados**, selecione um percurso salvo e use
**Executar percurso selecionado**. Posicione o personagem no mapa de origem
indicado no cadastro; ele percorre o caminho e termina ao chegar ao quadro, sem
abrir a conversa nem iniciar combate.

Marque as missoes desejadas na lista (caixa ao lado de cada uma, ou **Marcar
todas** / **Desmarcar todas**) e use **Executar: pegar missoes marcadas** ou
**Executar: entregar/completar marcadas**. Desmarcar tira a missao da execucao sem
apagar o cadastro; **Excluir missao** apaga o cadastro. Sem nenhuma marcada, executa a
missao selecionada. As marcadas do mesmo quadro sao feitas na mesma visita, uma por
vez, cada uma com sua confirmacao, e o Retorno e usado uma vez no final. A selecao fica
salva. O teste usa os acessos salvos se precisar chegar ao
quadro, executa a etapa escolhida, exige sua mensagem de sucesso e retorna pelo
NPC Retorno. Nao inicia caca e nao executa a outra etapa. Esses botoes
fazem a aceitacao/entrega real no jogo; completar nao simula mortes nem ignora
exigencias do servidor. A gravacao da outra etapa nao e necessaria para testar
uma que ja esta pronta.

Em **Fila de rotas**, **Executar somente viagem** valida o caminho ate o mapa dos
monstros e termina antes de iniciar combate. **Parar teste**, a tecla de iniciar/parar e Pausar
interrompem os novos envios. O resultado aparece no painel; falta de confirmacao
e tratada como falha, nao como sucesso. Pare a fila e encerre qualquer gravacao
antes de executar um teste.

### Gravar todos os menus recebidos, sem aceitar uma missao

1. Escolha o quadro e fique parado ao lado dele.
2. Clique em **Gravar menus do quadro**; abra a conversa no jogo.
3. Abra as categorias/submenus que deseja cadastrar, usando Voltar quando houver.
   Todas as opcoes de cada menu recebido sao guardadas, inclusive as nao clicadas.
4. Feche a conversa e clique em **Salvar gravacao compartilhada**. Este modo nao
   pede mensagem de aceitacao e nao exige criar uma missao antes.
5. Clique em **Selecionar missoes das opcoes salvas** e marque apenas os nomes das
   missoes desejadas. O restante do catalogo fica salvo para escolher depois.

O servidor so envia os menus que voce abre: gravar o primeiro menu nao descobre
sozinho submenus ainda nao recebidos. Evite confirmar aceitacoes se estiver apenas
catalogando. Os nomes selecionados viram cadastros de missao. Quando houver um
modelo compativel do quadro, suas sequencias sao reutilizadas com rank e slot
dinamicos; caso contrario, grave as sequencias especificas de pegar/entregar.
Teste pelos botoes isolados antes de usar a fila completa.

Abra **Rota de quests → Quadros e missoes compartilhados**. Os dois locais ja
estao cadastrados. Os percursos e as conversas ficam separados e sao reutilizados
por todas as rotas; nao e necessario gravar a mesma conversa em cada rota.

### 1. Gravar o acesso ao Quadro da Sala Vip

1. Entre no personagem e posicione-o no ponto de origem, por exemplo o hospital.
2. Escolha **Quadro da Sala Vip** e clique em **Gravar novo percurso de acesso**.
3. Caminhe manualmente pelo portal para areia.
4. Acesse o NPC **Sala Vip em areia [144,195]**, usando as opcoes reais do jogo.
5. Ao chegar em **ra_in01**, caminhe ate o Quadro de Missoes **[219,95]**.
6. Pare ao lado dele, **sem abrir o quadro**, aguarde terminar de andar e clique
   em **Salvar gravacao compartilhada**.

Um acesso que comeca fora de ra_in01 precisa incluir o NPC Sala Vip. A gravacao
nao aceita pular diretamente para o quadro. Se voce ja estiver dentro de ra_in01,
o bot pode caminhar ate o quadro sem repetir a entrada da Sala Vip.

### 2. Gravar o acesso ao Quadro de Kakashi

Escolha **Quadro de Kakashi**, inicie uma nova gravacao, caminhe ate o NPC de
**hospital2 [16,74]**, acesse-o, entre em **kakashi** e caminhe ate o Quadro de
Missoes **[87,140]**. Salve ao lado do quadro, antes de abrir a conversa.

Voce pode cadastrar varios acessos para o mesmo quadro, partindo de mapas
diferentes. Grave tambem as ligacoes entre os quadros e os retornos dos mapas de
caca. Um acesso hospital → quadro nao ensina automaticamente a volta: sem uma
ligacao gravada a fila pausa, em vez de inventar um portal ou teletransporte.

### 3. Cadastrar as opcoes de cada missao

1. Fique parado ao lado do quadro escolhido.
2. Clique em **Nova missao**, informe o nome e selecione-a na lista.
3. Clique em **Gravar como pegar**; so entao abra o quadro no jogo.
4. Selecione a missao, confirme sua aceitacao e feche o dialogo. Nao caminhe nem
   acesse outro NPC durante esta gravacao.
5. Clique em **Salvar gravacao compartilhada**. Informe um trecho da mensagem
   que confirmou a aceitacao, nao apenas o nome da missao. O texto precisa ter
   aparecido em uma resposta real do quadro nessa gravacao.
6. Quando puder entrega-la no jogo, selecione a mesma missao e use **Gravar como
   entregar**. Faca a entrega manual, feche o dialogo e salve sua confirmacao.
7. Repita para as outras missoes, no quadro correspondente.

Cancelar o menu pode ser gravado para fechar uma conversa; isso sozinho nao
confirma aceitacao ou entrega. As opcoes dos menus recebidos sao guardadas. O botao
**Cadastrar opcoes vistas** permite selecionar outros nomes para cadastrar;
categorias, voltar e cancelar nao devem ser marcados como missoes. Cada nova
missao ainda precisa das suas gravacoes de pegar e entregar: ver o nome de uma
opcao nao ensina suas respostas seguintes.

### 4. Fazer uma rota usar o cadastro

Volte a **Fila de rotas → Editar rota**. Marque as missoes compartilhadas desejadas
e arraste para ordenar. Podem ser de um quadro ou dos dois. Cada item indica o
quadro a que pertence. Grave na rota apenas **Rota da quest** e ajuste monstros e
meta; coleta e entrega usarao os registros compartilhados.

A fila confirma individualmente todas as missoes selecionadas ao pegar, viaja e
caca ate atingir a meta, depois confirma cada entrega antes da proxima rota.
Uma resposta de outra missao ou de outro NPC nao libera a etapa. Se alterar uma
gravacao compartilhada, todas as rotas que a referenciam usarao a nova versao na
proxima execucao. Cadastros em uso nao sao editados durante a fila ativa.

Os registros ficam em `data/rede/quadros_missoes.json`, protegido do atualizador.
O rascunho Kamizuru deste computador foi vinculado a uma missao ainda nao gravada
do Quadro da Sala Vip. As configuracoes anteriores foram preservadas.

## Ciclo completo por rota

As instrucoes abaixo tambem descrevem o modo anterior, de trechos particulares
por rota. Ele continua disponivel para configuracoes antigas. Se uma rota tiver
missoes compartilhadas marcadas, estas substituem sua coleta e entrega particulares.

Cada rota pode executar **Pegar quests → Viajar → Matar monstros → Entregar quests**.
Em **Editar rota**, marque o ciclo completo e configure os tres trechos em abas
separadas: **1. Pegar quests**, **2. Rota da quest** e **4. Entregar quests**.
A fase 3 usa a meta de mortes configurada. Atingir a meta inicia a entrega,
incluindo o caminho de retorno; so a entrega confirmada libera a proxima rota.

Na tela principal da aba, escolha o trecho no seletor ao lado de **Gravar trecho
selecionado**. Grave cada um separadamente, incluindo os caminhos, NPCs, menus e
fechamento dos dialogos. Ao salvar coleta ou entrega, informe um trecho da mensagem
de sucesso que o NPC mostrou. O gravador exige que o texto tenha sido recebido
durante aquela gravacao. Nas execucoes seguintes, a mensagem deve aparecer novamente
como resposta do NPC acessado; texto de outra etapa ou de outro NPC nao confirma.
Sem confirmacao, a fila pausa e nao considera que pegou ou entregou a quest.

O editor inclui atalhos para os locais informados:

| Local | Mapa | Coordenadas |
|---|---|---|
| Quadro de Missoes da Sala Vip | ra_in01 | 219,95 |
| Entrada para Kakashi, NPC sem nome informado | hospital2 | 16,74 |
| Quadro de Missoes de Kakashi | kakashi | 87,140 |

Escolha o NPC e clique em **Inserir NPC na etapa aberta**. Isso insere o local;
nao inventa as opcoes dos menus nem o caminho de retorno. Para o acesso hospital2
→ kakashi, grave o dialogo real e a chegada ao mapa. O rascunho Kamizuru usa o
quadro da Sala Vip como referencia inicial e continua desmarcado ate ser gravado.

Rotas anteriores continuam preservadas como somente viagem/caca. Marque o ciclo
completo para adicionar coleta e entrega; se faltar um trecho ou sua mensagem de
sucesso, o painel impede iniciar a fila.

## Usar a fila

1. Reabra o painel e entre no personagem pelo perfil local do bot.
2. Abra **Rota de quests**. Crie uma quest ou edite uma existente.
3. Escolha o mapa, os monstros e a quantidade total de mortes. A meta pode ser
   alterada em **Editar rota → Mortes para concluir**.
4. Marque as quests desejadas e use **Subir/Descer** para organizar a ordem.
5. Clique em **Executar fila marcada**. Ao chegar ao destino, o bot usa o combate
   configurado para os monstros da quest. No ciclo completo, atingir a meta inicia
   a entrega; apenas sua confirmacao libera a proxima rota.

**Iniciar**, no cabecalho, inicia a caca normal; a fila tem seu proprio botao.
A tecla de iniciar/parar e Pausar interrompem a fila. Ao parar/concluir, os alvos anteriores sao
restaurados. A fila nao reinicia sozinha apos fechar o painel ou uma desconexao.

## Gravar o caminho uma vez

1. Crie/salve a quest e selecione-a na lista.
2. Posicione o personagem no mapa de origem, por exemplo o hospital.
3. Selecione **Rota da quest** e clique em **Gravar trecho selecionado**.
4. Caminhe manualmente, entre nos portais e converse com os NPCs, selecionando as
   opcoes reais do jogo. A caca fica pausada durante esta gravacao.
5. No mapa final, clique em **Salvar trecho gravado**. O mapa recebido passa a ser
   o destino. Edite a quest para conferir monstros e meta antes de marca-la.

A gravacao substitui somente o trecho selecionado daquela quest. **Descartar
gravacao** conserva a rota anterior. Nao sao salvos login, senha, chat, compras ou
pacotes arbitrarios. Dialogos que pedem texto, numeros ou compras ainda nao sao
suportados e impedem salvar uma gravacao incompleta.

Os NPCs sao localizados novamente por coordenada e nome recebido; se a coordenada
salva estiver ate 2 celulas fora, vale o NPC de mesmo nome ao lado. As opcoes sao
procuradas pelo texto completo recebido; se mudarem ou forem ambiguas, a rota para
em vez de escolher um numero antigo. Proximo/Fechar aguardam a resposta do NPC.
Depois do clique, a conversa e seguida mesmo que o servidor responda com outro ID de
NPC (NPCs duplicados como "Sala Vip#2"); a mensagem de sucesso de uma missao continua
tendo que vir do NPC acessado. Se o Proximo ja foi apertado, o bot segue para o menu.
Cada clique, Proximo e opcao enviados aparecem no console do relay como `[ROTA]`,
assim como o motivo de qualquer parada.

## Conexoes entre mapas

As conexoes gravadas sao direcionais: ida nao prova a existencia de volta.
O bot combina trechos de outras rotas salvas, inclusive desmarcadas, para chegar
ao proximo destino. Se faltar uma conexao, a fila informa o trecho ausente.
Para ensinar o retorno, crie outra rota, grave o retorno e deixe-a desmarcada se
ela servir apenas como conexao. Se o personagem ja estiver no destino, a quest
comeca a caca sem repetir os teletransportes.

Durante a viagem, o mapa de colisao precisa estar disponivel. Apenas o portal
explicitamente selecionado pela etapa e liberado; os outros continuam evitados.
Sem progresso, sem resposta, mapa inesperado ou enquadramento de pacote invalido
pausam a fila. A presenca de jogadores e o controle manual continuam respeitados.

## Exemplo Kamizuru

Foi cadastrado neste computador um **rascunho desmarcado** para `anthell02`, com
meta editavel de **50 mortes somadas** de Dragao Mutante (1262), Inseto Assassino
(1294), Gremlin (1632) e Louva-a-Deus (1139), conferidos na base local.

Percurso informado: hospital → areia → Sala Vip [144,195] → ra_in01 → Viajante
Ninja [217,86] → Esconderijo do Cla Kamizuru Nivel 2 → anthell01 → portal [250,35]
→ anthell02. Falta gravar o portal do hospital e as etapas reais dos dialogos;
o rascunho exige essa gravacao antes de executar.

## @voltar e montaria

Em **Fila de rotas → Ao terminar a caca e na locomocao**:

- **@voltar**: clique em **Aprender @voltar** e digite `@voltar` no chat do jogo uma vez.
  O bot guarda o pacote que o jogo enviou e o repete (trocando so o nome se outro
  personagem estiver jogando). Com a opcao marcada, ao fechar os contadores o bot para,
  mata os monstros num raio (padrao 8 celulas), espera o tempo sem combate (padrao 6 s)
  e usa o @voltar. Dano fisico durante a conjuracao a cancela: o bot mata quem atacou,
  espera de novo e repete (ate 6 vezes). So segue para a entrega depois de o servidor
  confirmar a troca de mapa.
- **Montaria**: clique em **Aprender montaria** e equipe a montaria no jogo, fora de
  combate. O bot guarda o item e quais equipamentos o servidor tirou para ela. Com a
  opcao marcada, antes de cada deslocamento (ir aos quadros, ao mapa de caca, entregar)
  ele equipa a montaria do mesmo jeito do @voltar (mata os monstros ao redor, espera
  sair de combate, tenta de novo se o servidor recusar). Ao chegar no mapa de caca, antes
  de atacar, recoloca os equipamentos que a montaria tirou; no proximo deslocamento,
  a montaria volta.

**Switch** abre uma janela com duas abas. **Montaria**: todas as montarias do inventario
(descricao com "montaria" ou item que ocupa baixo, mao direita e mao esquerda); escolha uma.
**Equipamentos**: os equipamentos de baixo, mao direita e mao esquerda (o que a montaria
tira) e a municao (kunai/shuriken; marque so uma). Salvar so guarda a escolha, por
personagem; a fila a usa: montaria nos deslocamentos, equipamentos ao comecar a caca.

O @voltar conjura a habilidade 960 do servidor. Se o servidor recusar (em combate), o bot
espera de novo o tempo sem combate inteiro (padrao 10 s, contado do ultimo golpe dado ou
recebido) antes de repetir. Quando a conjuracao comeca, espera o tempo que o servidor
informar. As respostas do servidor nos 15 s apos cada @voltar ficam em
`respostas_voltar.jsonl`, na pasta da sessao em `logs/relay`.

Se o jogo mostrar mensagens de combate ("entrou/saiu de combate", "aguarde N segundos"),
o bot as usa: com "saiu de combate" age na hora; uma recusa conta como tentativa cancelada.
As mensagens aparecem no console como `[ROTA] Jogo: ...`. Sem elas, vale o tempo sem combate.

Na caca da quest, um monstro que ataca o personagem passa a ser atacado tambem ate o fim
da rota, mesmo que nao seja alvo de nenhuma missao (ex.: Inseto Assassino em anthell02).

Os ajustes ficam em `data/rede/quest_extras.json`. No console, cada passo aparece como
`[ROTA] @voltar: ...`, `[ROTA] Montaria: ...` ou `[ROTA] Equipamentos: ...`.

## Parada por GM

Param tudo (envios bloqueados, alerta na tela, so volta ao iniciar): @hide confirmado,
personagem da lista de observacao e GM/staff na tela. GM/staff e reconhecido por: marca no
nome, guilda, grupo ou cargo ("GM", "[GM]", "ADM", "Admin", "Staff", "Mod", "Suporte"),
velocidade anormal (ate 40 ms por celula; o normal e 150), dois teleportes seguidos perto
de voce em 30 s, ou um visual/marca listado em `data/jogadores/gm_sinais.json`:

    {"visuais": [5038, 1224], "marcas": ["Hokage"]}

`visuais` sao IDs de arma, escudo ou visual de cabeca (veja-os passando o mouse sobre o nome
na aba Jogadores); `marcas` sao textos extras de nome.

## Encadear rotas (varios mapas, uma coleta e uma entrega)

Em **Editar rota**, marque **Encadear com a proxima rota da fila**. Rotas seguidas assim
formam uma cadeia: o bot pega as missoes de todas de uma vez, caca no mapa da primeira ate
fechar os monstros dela, segue para o mapa da proxima (usando o @voltar se nao houver
caminho gravado de um mapa de caca para o outro), e depois do ultimo mapa volta e entrega
todas. Na lista da fila, a rota encadeada aparece com "⛓". Ao escolher o mapa de caca, as
missoes com monstros daquele mapa ficam com fundo verde na lista.

## Retomar a fila

O progresso da fila (rota, etapa, missoes pegas/entregues/puladas, contador de monstros)
fica salvo em `data/rede/progresso_quests.json` a cada poucos segundos e a cada parada.
**Retomar fila** continua dali: na caca, volta ao mapa de caca com o contador mantido;
na coleta/entrega, segue da proxima missao que falta.

## Gravacao enxuta das rotas

Ao salvar uma rota de mapa, um acesso ao quadro ou a rota da quest, o bot guarda so:
os NPCs com quem falar e as opcoes escolhidas, em cada mapa o ponto de saida para o
proximo (portal, ou o ultimo ponto quando a saida e caminhando) e o destino final. Os
cliques de caminhada nao sao guardados: a cada execucao o bot calcula o caminho mais curto
ate cada ponto, pela colisao do mapa. As rotas antigas foram compactadas (copia em
`backups/rotas-20261103`).

## Patrulha da caca

Em **Configuracao**: **Distancia entre pontos** (6 a 40 celulas; pontos por onde ja
passou perto, a 3/4 dessa distancia, nao sao revisitados), **Cobrir do mapa antes de
recomecar** (30 a 100%) e **Ignorar pontos proximos a paredes** com a **Distancia minima
da parede**. Mudar esses valores refaz os pontos de cada mapa, mantendo o que ja foi andado.

## Opcoes de caca da rota

- **Ignorar os monstros que ja completaram e os que nao sao da quest**: a caca ataca so o
  que ainda falta. **Nao ignorar (atacar sempre)** lista os monstros do mapa de caca:
  marque o que da problema (ex.: o agressivo) para ataca-lo sempre. Sem a opcao, todos os
  monstros contados e quem atacar o personagem continuam sendo atacados.
- O contador aparece dentro do jogo, no canto superior direito: feitos/necessarios e
  quantos faltam de cada monstro.
- Presenca de jogadores so pausa durante o combate; deslocamentos, montaria, troca de
  equipamentos e @voltar continuam.
- Antes do @voltar e da montaria, o bot mata so os monstros que estao atacando o
  personagem; os pacificos ao redor sao deixados em paz.
- Se nao houver caminho gravado a partir do mapa atual (ex.: do mapa de caca ate os
  quadros), o bot usa o @voltar aprendido (mesmo com a opcao desmarcada). Se ainda assim
  parar, leve o personagem a um mapa com caminho gravado (ex.: @voltar manual): a fila
  continua sozinha.
- **Configuracao → Movimentacao manual**: voce anda pelo mapa; o bot so combate e seus
  cliques no chao nao o pausam.

## Contador por monstro

Em **Editar rota**, marque as missoes e use **Preencher pelas missoes marcadas** (ou
**Usar monstros das missoes marcadas nesta rota**). A tabela recebe um contador por
monstro a partir de "Monstros necessarios" de cada missao, por exemplo 50 Louva-a-Deus
e 50 Gremlin. Um monstro pedido por duas missoes conta uma vez, com a maior quantidade,
como o servidor conta. A tabela pode ser editada (monstro, quantidade, IDs).

Na caca, todos os monstros da rota continuam sendo atacados, inclusive os que ja
chegaram a quantidade; a entrega so comeca quando todos os contadores estiverem
completos. O andamento aparece em **Fila de rotas** ("Louva-a-Deus 32/50 | Gremlin 50/50 ✓").
Sem contador, vale o total em "Mortes (sem contador)". Se o nome de um monstro da
missao nao tiver ID conhecido, a fila pede para vincula-lo em **Configurar rank e monstros**.

## Contagem e armazenamento

A contagem local exige dano positivo do proprio personagem em um monstro
configurado e remocao com motivo de morte enviado pelo servidor. Sair da tela,
teletransportar ou apenas enviar ataque nao contam. Se outro jogador causar o
ultimo dano observado, a morte nao entra na meta. Esta contagem nao substitui o
contador oficial de uma quest do servidor e nao conta mortes de invocacoes sem
atribuicao ao personagem. Progresso da execucao fica nesta sessao; as rotas e suas
configuracoes permanecem em `data/rede/rotas_quests.json`, protegido de atualizacoes.

Formatos de dialogo conferidos com a tabela do cliente local e com a
[implementacao de NPCs do rAthena](https://github.com/rathena/rathena/blob/master/src/map/clif.cpp).
Essa referencia nao substitui a validacao do percurso completo no NRO.

## Quests para todos os usuários

Ao publicar, as quests, os quadros e missões, as rotas de mapa e os portais (inclusive os
internos) do desenvolvedor vão juntos em `data/compartilhado`. No PC de cada usuário, ao
atualizar ou abrir o painel, esses dados são mesclados uma vez por publicação:

- o que veio publicado substitui a cópia anterior do mesmo item (mesmo id, mesma missão do
  quadro ou mesmo percurso origem → destino);
- o que o usuário criou continua, e a escolha de ativar ou não cada quest na fila é mantida;
- antes de mesclar, os arquivos do usuário são copiados para `backups/antes-dos-dados-compartilhados-*.zip`.

A base de monstros também vai (`data/monstros_base`: IDs, nomes por mapa, HP e sprites). As
configurações de caça, combate e habilidades, inclusive os alvos da aba Monstros, nunca vão: cada
PC mantém as suas, por personagem (veja `docs/ATUALIZACOES.md`).

Não são compartilhados: missões concluídas no dia, vagas, progresso da fila, @voltar
aprendido, Switch (montaria e equipamentos de cada personagem) e login.


### Retomada da ca?a e observa??o durante percursos (2026-11-05)

A etapa de ca?a ativa a patrulha para buscar os monstros pendentes, mesmo quando a
patrulha comum estava desmarcada. A op??o de movimento manual continua respeitada.
Um destino de `@showmobs` sem progresso por 25 segundos deixa de prender a busca:
o personagem volta ao circuito de explora??o.

Durante coleta, viagens, entrega, retorno e prepara??o de equipamentos, o observador
de jogadores fica suspenso, sem alterar a lista ou a op??o salva. Ao entrar na etapa
de ca?a, os jogadores presentes voltam a ser verificados antes do combate.

## Reexecutar concluídas, viagem isolada e busca agregada

Rotas cujas missões foram todas concluídas hoje começam desmarcadas para o
personagem atual. Marcar uma delas novamente permite repetir a viagem e a caça,
com novos contadores de execução, mantendo o histórico diário. Como o servidor
pode recusar uma missão diária já entregue, essa reexecução não tenta obter ou
entregar novamente as diárias concluídas. A retomada preserva a fila e esse modo,
mesmo que as rotas tenham sido desmarcadas ao reabrir o painel.

**Executar somente viagem** está disponível a todos os usuários conectados, sem
requisito de personagem ou perfil de desenvolvedor. O teste monta primeiro a
conexão entre o mapa atual e a origem do percurso, utilizando os caminhos aos
quadros, as ligações entre mapas e as rotas compartilhadas. Por exemplo, uma rota
que começa na Sala VIP pode usar o acesso Hospital → Areia → Sala VIP antes do
trajeto de caça. Se não houver ligação registrada, o teste pausa e informa o
caminho faltante; não inicia um percurso parcial com a origem errada.

O editor usa um índice dos monstros carregado uma vez por abertura, preservando
as regras de distinguir nomes que compartilham sprite e de excluir invocações.
Num teste local comparando a implementação anterior e a nova sem profiler,
a abertura caiu de 3,175 s para 0,298 s. O tempo varia com a base e o computador.

A busca `@showmobs` reúne as respostas dos monstros ainda necessários da quest.
A mesma entidade não é contada duas vezes; grupos são avaliados pela soma dos
tipos consultados. Áreas inacessíveis são descartadas e o destino resultante vai
para o planejador de caminhos. Monstros de quest encontrados no trajeto continuam
sendo combatidos normalmente. As consultas são espaçadas; o snapshot não equivale
a rastreamento contínuo de todos os monstros do mapa.

### Escolha do percurso de viagem

A execução compara portais cruzados, transportes de NPC e percursos registrados
para chegar ao destino da etapa. Considera a posição atual, a caminhada até os
acessos, as chegadas conhecidas e a aproximação ao quadro de missões. Quando há
colisão disponível, a estimativa de caminhada respeita as paredes; sem coordenada
de chegada ou mapa legível, usa uma estimativa conservadora.

O caminho gravado continua como uma opção conhecida, mas não obriga o bot a
repeti-lo quando há alternativa mais próxima. Conversas de coleta e entrega são
preservadas. O percurso é escolhido ao preparar a etapa e não fica sendo trocado
a cada instante durante a caminhada. O `@showmobs` automático permanece suspenso.
