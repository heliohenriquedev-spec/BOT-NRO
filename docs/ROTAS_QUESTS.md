# Rota de quests

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
monstros e termina antes de iniciar combate. **Parar teste**, Home, F12 e Pausar
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
Home, Pausar e F12 interrompem a fila. Ao parar/concluir, os alvos anteriores sao
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
