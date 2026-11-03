# BOT NRO

Bot de caça para o Naruto Redemption Online que funciona por pacotes: o jogo conecta no
bot (no próprio PC) e o bot repassa a conexão ao servidor, lendo o que acontece e enviando
as ações de combate e movimento.

## Requisitos

- Windows 10 ou 11
- [Python 3.12](https://www.python.org/downloads/), com a opção **Add python.exe to PATH** marcada
- O jogo instalado em `C:\NRO - Jogo COMPLETO`

## Instalação

1. Baixe o bot: botão verde **Code → Download ZIP** nesta página e extraia numa pasta,
   por exemplo `C:\BOT NRO`.
2. Execute **`instalar.bat`**. Ele cria o ambiente Python, instala as dependências e
   adiciona ao jogo a entrada de servidor **NRO - BOT LOCAL**.
   Os arquivos originais do jogo ficam guardados em `backups\`, e
   **`RESTAURAR_CONEXAO_ORIGINAL.bat`** desfaz essa alteração.

## Uso

1. Execute **`INICIAR_BOT.bat`** e clique **Abrir conexão**.
2. No jogo, escolha o servidor **NRO - BOT LOCAL** e entre no personagem.
3. Configure alvos e habilidades nas abas **Configuração**, **Habilidades** e **Prioridade**.
4. **Home** inicia ou pausa a caça e **F12** bloqueia todos os envios do bot.

Clicar no chão para andar só pausa o bot enquanto você está no controle: ele volta sozinho
3 segundos depois do último clique.

### Minimapa

O minimapa fica no canto do jogo e mostra o caminho já feito (azul), os pontos que faltam
visitar (verde), a rota atual (amarelo) e os jogadores por perto, inclusive os escondidos
(vermelho). Os botões **+** e **−** mudam o tamanho, a roda do mouse dá zoom e dá para
arrastá-lo para outro lugar. Para desligá-lo, use a opção na aba **Prioridade**.

### Capturar um jogador como alvo

Na aba **Prioridade**, clique **Capturar jogador com o mouse do jogo**. Nos 20 segundos
seguintes, passe o mouse do jogo sobre o jogador ou clique nele.

### Mapas sem colisão

A maioria dos mapas é lida direto dos arquivos do jogo, mas cerca de 70 deles são
criptografados. Para esses, coloque o `map_cache.dat` (rAthena) ou os `.mcache` (Hercules)
do servidor na pasta `data\mapas`.

## Atualizar

Abra a aba **Atualização** do painel. O bot avisa quando há versão nova; feche a conexão e
clique **Atualizar agora**. Ele baixa a versão nova daqui do GitHub e reinicia o painel.
Suas configurações, os buffs aprendidos, a conexão local e os registros são preservados.

## Para o desenvolvedor

Numa cópia clonada com `git` e com permissão de envio, a aba **Atualização** também mostra
**Publicar atualização**. Basta descrever o que mudou: o bot roda os testes (`tests\`),
aumenta a versão em `versao.json`, faz o commit e envia para o GitHub. Quem tem o bot
instalado vê a versão nova na próxima vez que abrir o painel.

- Testes: `.venv\Scripts\python.exe -m pytest tests`
- Validação da patrulha em todos os mapas: `.venv\Scripts\python.exe tools\validar_patrulha.py`

O arquivo `nrobot/grf_header.py` adapta código do [rAthena](https://github.com/rathena/rathena),
distribuído sob a licença em `third_party/rathena/LICENCE`.


### Ajustes locais de presenca e distancia (2026-11-02)

Em Configuracao, a lista de jogadores permitidos aceita um nome exato por linha,
sem diferenciar maiusculas/minusculas. A excecao passa a valer quando o servidor
informa o nome; outros jogadores continuam pausando normalmente. A lista e salva
com as configuracoes do painel.

A retomada por presenca usa o intervalo configurado depois da saida do raio de
visao ou remocao do jogador. Uma nova aproximacao reinicia a espera. Sinais explicitos
de invisibilidade continuam usando a retencao propria de furtividade. Pausas manuais
nao sao desfeitas automaticamente. Se o comando de levantar nao puder ser enviado,
o bot aguarda e tenta novamente antes de liberar a caca.

Com habilidades ofensivas de longo alcance habilitadas e utilizaveis, o movimento
mantem distancia mesmo com ataques basicos ligados. O recuo respeita colisao,
linha de visao e alcance; ataques basicos continuam limitados ao proprio alcance.
Estas alteracoes exigem reiniciar o painel e reconectar o personagem ao relay.


### Modos e alcance das habilidades

A lista de jogadores permitidos inicia bloqueada. Clique em **Editar jogadores
permitidos** para alterar e em **Concluir e bloquear lista** ao terminar.

Na aba Habilidades, apenas habilidades aprendidas recebem controles. O papel pode
ser ofensiva no alvo, ofensiva em si (para tipos de uso em si/suporte), buff em si,
ou invocacao no chao (para habilidades de chao). Uma ofensiva em si exige um alvo
proximo, mas envia o ID do proprio personagem. Ela nao precisa de vinculo de buff.
A confirmacao de dano continua exigindo resposta do servidor da mesma habilidade.

Invocacoes usam uma celula livre ao lado do personagem, ou a propria celula se for
necessario. Exigem colisao disponivel, alcance valido, SP, cooldown e delay. O
intervalo configurado e respeitado mesmo no modo rapido/rajada; novas habilidades
de chao ficam desmarcadas e usam inicialmente 30 segundos. Uma resposta sem dano
com sucesso confirma execucao, nao dano nem duracao da invocacao. Na ausencia de
resposta reconhecida, o intervalo e preservado para evitar repeticao imediata.

**Alcance (celulas)** inicia em **Jogo (N)**. Um valor numerico substitui o limite
local de aproximacao e de tentativa de uso. Voltar ao minimo restaura o padrao do
jogo. Isso nao altera o alcance aceito pelo servidor. Habilidades em si com alcance
recebido zero nao informam raio de dano: usa-se uma proximidade conservadora de 2
celulas para ativar, que pode ser ajustada. Buffs em si nao precisam de distancia
ate um monstro.

O formato 0113 de chao foi conferido por leitura estatica do cliente local;
a evidencia esta em data/rede/habilidades_chao_validacao.json. O uso real das novas
habilidades ainda precisa ser validado no jogo apos reiniciar o painel e reconectar.


### Fila exclusiva Kuchiyose e duracao

Na aba Habilidades, **Marcar Kuchiyose aprendidas para a fila** seleciona apenas
habilidades aprendidas cujo nome local contem Kuchiyose e cujo tipo do servidor
permite execucao em si ou no chao. Outras habilidades de chao nao entram sozinhas.
As colunas **Prioridade invocacao** (menor primeiro) e **Duracao invocacao (s)**
configuram a fila. Depois do termino, a fila passa para a proxima disponivel e
reinicia o ciclo quando chega ao fim. SP, cooldown e delay continuam obrigatorios;
portanto pode haver um intervalo sem invocacao se nenhuma estiver disponivel.

O bot reserva a fila no envio e acompanha somente uma invocacao por vez, inclusive
em rajada. Confirmacoes e efeitos sao fatos separados. Uma resposta de sucesso
pode confirmar a execucao; um efeito proprio vinculado confirma atividade e seu
termino libera a proxima invocacao. O efeito e associado automaticamente apenas
apos uma resposta de sucesso da habilidade, quando ha um unico efeito novo na
janela observada. Respostas ambiguas ou outra habilidade nessa janela nao criam
vinculo. Remover uma animacao de chao nao prova que o ser invocado morreu.

**Duracao 0** aguarda o efeito vinculado. Caso nao haja sinal identificavel, a fila
mostra duracao desconhecida e nao cria outra invocacao cegamente. Voce pode informar
uma duracao conhecida ou, depois de verificar no jogo que a invocacao realmente
terminou, clicar **A invocacao terminou no jogo: confirmar fim e aprender duracao**.
Essa medicao assistida passa a ser o temporizador dos proximos usos quando nao ha
efeito vinculado; ela e uma duracao observada, nao um prazo nominal enviado pelo
servidor. A medicao manual e recusada se o servidor ainda informa o efeito ativo.

O fim observado de um efeito mede sua duracao real naquele uso (podendo terminar
antes por cancelamento), sem confundir o tempo com cooldown nem afirmar que toda
invocacao tem o mesmo prazo. Com duracao 0, o efeito vinculado acompanha o termino. Uma duracao explicitamente
configurada determina o limite de ocupacao da fila. Os dados ficam em **data/rede/invocacoes_aprendidas.json**,
separados por habilidade e nivel, protegidos da atualizacao e fora da publicacao.
Mudancas de configuracao/pausa preservam a invocacao acompanhada; trocar de mapa
limpa a presenca local e mantem os dados aprendidos. O funcionamento ao vivo das
Kuchiyose ainda precisa ser validado: a descricao local de Filhote Katsuyu nao
informa tempo e os registros anteriores nao fornecem uma duracao confirmada.


### Kuchiyose no modal e combate com movimentacao livre

O botao **Marcar Kuchiyose aprendidas para a fila** agora abre um modal com somente
as Kuchiyose aprendidas. Elas ficam ocultas na tabela geral e nao sao marcadas pelo
botao de ofensivas. No modal, selecione Usar e configure duracao, recarga local e
prioridade; Salvar aplica as alteracoes, Cancelar preserva os valores anteriores.
A duracao e a recarga sao controles distintos. Uma recarga maior informada pelo
servidor prevalece sobre o numero local.

Modos da fila:
- **Ciclo continuo**: percorre as habilitadas, pulando indisponiveis, e depois reinicia.
- **Prioridade disponivel**: ao terminar a ativa, escolhe a de maior prioridade que
  ja esteja pronta; pode voltar a 1 antes de usar 3 (por exemplo 1, 2, 1, 3).

Mudar o modo nao substitui uma invocacao ativa. Cada nova invocacao exige um monstro
alvo recente a ate 12 celulas da posicao atual estimada, e linha livre. Alcance de
conjuracao, celula livre, SP e recarga sao validados novamente antes do envio. Sem
monstro proximo, a fila espera. Um jogador capturado nao satisfaz essa condicao.

Com ataque basico desligado, o bot mantem o recuo no alcance das habilidades. O
movimento nao e mais descartado por espera global de habilidades ou por conjuracao;
o pacote de movimento pode seguir o de habilidade na mesma passagem do controle.
O trajeto confirmado nao e apagado pelo inicio da conjuracao. O servidor pode
corrigir o movimento, e essas correcoes continuam sendo respeitadas.

Com ataque basico ligado, o personagem se aproxima do alcance de ataque e intercala
ataques basicos com as habilidades. A espera calculada pelo tempo de animacao da
sprite nao bloqueia a rotacao configurada. Cooldown, delay entre habilidades,
conjuracao ainda em andamento para iniciar outro uso e verificacao de alcance
continuam independentes. As alteracoes precisam de reinicio do painel e reconexao;
os testes locais nao substituem a validacao de movimentacao livre no servidor.


### Correcao da aproximacao ao alternar ataque basico

Com colisao carregada, planejamento e envio do ataque basico usam a mesma regra:
celula adjacente com passagem livre (sem atravessar canto bloqueado), ou a mesma
celula. Estar a duas celulas nao basta para planejar ataque: o bot da o passo que
falta. A escolha do final de cada segmento usa a mesma verificacao. Habilidades
mantem seus alcances configurados. Ataque basico desligado continua usando recuo;
ligado continua aproximando para intercalar ataques. A validacao de um pacote
que ficou desatualizado recalcula a acao sem excluir o alvo temporariamente.


### Recuo em alcance menos uma celula e origem da posicao

Com ataque basico desligado, habilidades de alcance 6 usam distancia de navegacao
5 (alcance configurado menos 1); a autorizacao da habilidade continua respeitando
seu alcance original. O recuo procura celulas livres nessa distancia e nao reutiliza
segmentos/celulas de falha recente. A duracao estimada da caminhada considera o
custo diagonal para nao iniciar o proximo trecho cedo demais.

A celula recebida no ultimo pacote e mantida separada do destino anunciado e da
estimativa durante o movimento. Uma correcao 0088 substitui a previsao anterior.
Uma caminhada propria recebida por 0086 preserva destino/trajeto e pode confirmar
o passo pendente; nao e tratada como parada. Aparicoes em movimento calculam rota
sobre a colisao; sem rota resolvida, o bot mantem os extremos recebidos e indica
incerteza em vez de inventar uma celula em linha reta atraves de paredes.

Em Estado da caca, a distancia do alvo usa a estimativa atual do personagem, nao
seu destino de caminhada futuro. Os campos de posicao recebida e destino anunciado
permitem comparar a origem dos dados. O servidor nao envia cada celula intermediaria:
previsoes de trajetoria continuam sendo estimativas, mesmo quando baseadas em pacotes.


### Prioridade da manutencao Kuchiyose durante o recuo

Para Kuchiyose habilitadas e aprendidas, sem invocacao ativa ou na hora de uma
nova tentativa, a manutencao tem prioridade sobre ofensivas e ataques basicos.
Os pedidos ofensivos aguardam a invocacao, inclusive quando e necessario reservar
SP ou esperar a recarga. Depois da execucao/confirmacao ou da tentativa acompanhada,
o combate continua. Isso nao garante atividade quando faltam SP, recarga ou uma
confirmacao reconhecida; tentativas sem duracao conhecida seguem o intervalo ja
configurado, sem registrar como fato que a invocacao terminou.

Se o alcance ofensivo permitir recuar alem da proximidade de invocacao, o alcance
de navegacao e limitado temporariamente a 11 celulas ate a manutencao, mantendo a
exigencia de monstro alvo a ate 12 celulas. Uma vez acompanhada a invocacao, volta
a distancia ofensiva configurada. Um alvo antigo/longe nao impede escolher outro
monstro alvo proximo e recente para autorizar a invocacao.

Para invocacoes no chao, a validacao de tiro do monstro nao e aplicada como se ele
fosse o destino da habilidade: validam-se a proximidade do monstro e a celula de
conjuracao proxima ao personagem, com colisao e alcance proprios. Se uma habilidade
de chao de alcance zero nao tiver celula atual segura durante a caminhada, o bot
aguarda a estabilizacao do trecho, prioriza a invocacao e depois retoma o recuo.
Estas regras ficam no codigo compartilhado; nao dependem da configuracao observada
na maquina local. Cada usuario ainda escolhe as Kuchiyose habilitadas no modal.


### Whitelist e registros de outros jogadores ocultos

O vinculo nome/ID recebido do servidor fica no cache da sessao e e sincronizado com
o filtro de presenca, inclusive apos trocar de mapa e antes de avaliar uma pausa.
A comparacao usa o nome completo, normaliza Unicode, maiusculas/minusculas e espacos;
nao permite correspondencias parciais. Um nome novo recebido substitui o anterior.
Antes de receber ou conhecer um nome, o ID continua desconhecido e pode suspender
a caca ate ser identificado. Nao sao enviadas consultas ativas novas de nomes.

Jogadores permitidos recebem **[PERMITIDO] ... whitelist; nao pausa**, em vez de
alerta vermelho. A excecao vale para jogador visivel, disfarce, ocultacao e espera
de saida. Isso nao desfaz pausas manuais nem libera outro jogador nao permitido.

Para outros jogadores, um sinal de ocultacao recebido mantem a ultima celula apos
a remocao visual. O destino final de uma caminhada nao substitui essa ultima celula
recebida. Um sinal de retorno, saida confirmada, troca de mapa ou expiracao limpa
o registro conforme o tipo de evento. O minimapa e um aviso transparente na tela
mostram nome, estado e ultima celula; nao se desenha uma silhueta sobre uma celula
de tela inventada, pois a projecao da camera/zoom dos outros personagens e desconhecida.
A silhueta central continua exclusiva do proprio personagem.

Se o jogador apenas desaparece perto, sem pacote que prove ocultacao, o marcador
e temporario e diz **@hide nao confirmado** ("?" no minimapa). A remocao isolada
nao prova @hide. Um jogador que ja entrou invisivel e nunca foi informado pelo
servidor nao pode ser localizado por estes dados. Os registros indicam ultima
posicao recebida, nao rastreamento atual de movimentos que o servidor nao envia.


### Separacao de duracao e recarga: exemplo 20 s / 46 s

Uma duracao explicita de 20 s libera a fila apos 20 s de atividade. Ela nao fica
esperando desaparecer um efeito vinculado automaticamente, pois esse efeito pode
ser um indicador de recarga, e nao da vida da invocacao. Vinculos automaticos antigos
nao sao importados para habilidades com duracao explicita; um efeito persistente
nao restaura silenciosamente a invocacao ja encerrada pelo temporizador.

A recarga de 46 s bloqueia somente a mesma habilidade e e contada desde seu envio.
Com A e B marcadas e prontas: A em t=0, B em t=20. A pode voltar a t=46 (nao t=66).
Se A e B duram 20 s e ambas recarregam em 46 s, em t=40 nenhuma pode estar pronta:
essa lacuna nao pode ser removida ignorando o cooldown. Uma terceira habilidade
pronta pode cobrir o periodo, conforme o modo de prioridade escolhido.

O modal explica a contagem, alerta sobre lacuna local prevista quando so uma esta
marcada e mostra a recarga restante de cada habilidade da sessao. SP, delay global,
proximidade de alvos e recarga efetivamente informada pelo servidor continuam
obrigatorios. O fluxo 20/46, com efeito ainda ativo aos 46, e coberto por testes
nos modos ciclo e prioridade; isso nao substitui validar o caso do outro usuario.


### Erro ao iniciar: No module named PySide6

Esse erro significa que o Python que esta abrindo o painel nao consegue importar
a biblioteca da interface. Uma pasta .venv existente nao garante instalacao completa.
Execute **instalar.bat** na pasta extraida do bot e, depois, **INICIAR_BOT.bat**.
Use os dois arquivos da mesma copia do projeto, sem copiar .venv de outro computador.

O inicializador agora verifica os imports QtCore, QtGui, QtWidgets e numpy com o
proprio .venv/Scripts/python.exe. Se faltar uma dependencia, chama o instalador
para reparar. O instalador prefere o launcher py -3.12 ao criar um ambiente e
aceita python 3.12 ou superior como alternativa. Verifica venv, pip e instalacao
de requirements; falhas encerram com erro antes de tentar abrir o painel. A
configuracao do jogo so e chamada depois da verificacao dos imports.

Se o pip nao conseguir baixar/instalar, envie o erro exibido por instalar.bat:
a mensagem original PySide6 ausente, sozinha, nao mostra a causa desse download.
A janela fica aberta em falhas na execucao manual; ao ser chamado pelo inicializador,
o erro volta ao inicializador, que tambem o mantem visivel. Nenhuma dependencia
e instalada no Python global por estes scripts.


### Primeira instalacao: habilidades vazias e SP None

A tabela de pacotes e validada contra **NRO.exe da pasta escolhida neste PC**, e
nao contra o caminho absoluto registrado na maquina que extraiu a tabela. O caminho
source_executable do JSON permanece somente como origem historica quando nao ha
pasta configurada; iniciar pelo painel/instalador usa a pasta escolhida. A verificacao
SHA-256 continua obrigatoria. Cliente diferente/arquivo ausente produz erro claro,
sem abrir uma sessao que aparenta funcionar mas perde os dados iniciais.

**instalar.bat** executa a verificacao de dependencias e, depois da configuracao do
perfil, **python -m nrobot.runtime_check --game**. Essa etapa verifica o executavel
local e a tabela distribuida. O inicializador do relay tambem verifica a tabela
antes de abrir a conexao. A tabela completa e runtime_check.py devem estar no pacote.

A lista inicial de habilidades, SP, atalhos, efeitos e velocidade sao preservados
quando a mesma sessao do personagem abre outra conexao de mapa. Dados espaciais
antigos sao descartados. Uma nova selecao de personagem ou login limpa os dados
anteriores para nao mostrar habilidades de outro personagem. A identidade propria
pode ser restaurada do ID de conta ja recebido no handshake, sem consultas ativas.

Os dois pacotes de parametro B0/B1 atualizam os dados de SP recebidos. Pacotes validos
antes de um trecho desconhecido nao sao descartados junto com esse trecho; uma
sequencia ainda desalinhada nao e interpretada como habilidades ou atributos.
Estado da caca mostra se identidade, lista e SP ja foram recebidos, para separar
"nenhuma habilidade aprendida" de "lista inicial ainda nao recebida".

Para um usuario que ja estava com lista vazia, atualizar o pacote/painel e entrar
novamente no personagem pelo perfil local reenvia os dados iniciais. Apenas trocar
a aba ou caminhar nao solicita outra lista ao servidor. Nao ha consultas novas
nem copia da lista de habilidades de outro usuario.


### Combate enquanto nenhuma Kuchiyose esta disponivel

A manutencao tem prioridade apenas quando uma invocacao habilitada e aprendida
pode ser tentada: recarga local e do servidor encerradas, SP suficiente e nenhuma
invocacao ativa bloqueando a fila. Sem nenhuma pronta, habilidades ofensivas e
ataques basicos continuam normalmente; a navegacao tambem usa seu alcance normal.
Uma tentativa de invocacao ja enviada ainda aguarda a confirmacao por tempo limitado.

Exemplo com apenas uma invocacao de 20 s e recarga 46 s: invoca em t=0; em t=20
termina e o combate continua; em t=46 ela volta a ter prioridade, se houver SP e
alvo valido. Nao e necessario habilitar uma segunda invocacao para o bot continuar
combatendo. Sem nenhuma invocacao marcada, o combate tambem segue normalmente.
Esta regra substitui a reserva de SP/espera de recarga descrita anteriormente.


### Reducao das pequenas esperas locais

Confirmacoes repetidas de caminhada nao reiniciam o temporizador de um trecho.
Quando o observador tem inicio/duracao do trajeto aceito, a espera usa esse fim
estimado, em vez de somar novamente o percurso ao instante de recebimento do ACK.
Uma correcao que confirma chegada prevalece sobre ACKs atrasados. Continua sendo
necessaria confirmacao da caminhada; a otimiza??o nao antecipa envios sem validacao.

Rotas A* de aproximacao so sao calculadas quando ha necessidade de caminhar: o
combate ja dentro do alcance nao recalcula a mesma rota a cada passagem do loop.
O estado rapido do painel permanece separado da lista historica completa de
entidades: esta lista e gravada em intervalos de um segundo, com atualizacao
imediata na troca de mapa e repeticao em caso de bloqueio temporario do arquivo.
O loop de acoes continua em 20 ms. Cooldowns, conjuracoes e pausas configuradas
por presenca/manual permanecem independentes dessas reducoes de espera local.


### Caca em grupo (computadores diferentes)

Em Configuracao, ative **Caca em grupo** em cada computador. No bot que conduz o
trajeto, selecione **Lider** e configure a caca normal (tambem pode caminhar a mao).
Nos demais, selecione **Seguidor**, informe o nome completo do mesmo lider e ajuste
a distancia (2 a 8 celulas). Informe os nomes dos outros membros em **Membros
permitidos**, um por linha, para que a presenca deles nao suspenda a caca. O lider
configurado tambem fica permitido. Isso nao cria uma PT no servidor: a PT do jogo
e organizada pelos jogadores e o lider e explicitamente escolhido no bot.

Sem **Apenas seguir**, o seguidor observa o ID do monstro atacado/conjurado pelo
lider nos pacotes recebidos e limita seu combate a esse ID. Outro monstro mais
perto nao substitui o alvo do lider. Configure os mesmos alvos permitidos de monstros
em todos os bots, ou identificacao automatica do mapa: alvos nao confirmados pelo
proprio seguidor nao autorizam ataques. Ao perder o alvo, segue o lider em vez de
iniciar patrulha independente. Se ficar muito distante, volta a seguir antes de
retomar o combate. Cooldowns, SP, colisao e verificacoes de alvo continuam locais.

Com **Apenas seguir** marcado, ficam bloqueados ataques basicos, habilidades e
invocacoes, inclusive na validacao imediatamente antes do envio. Pode marcar ou
desmarcar conforme desejar; aplicar configuracao pausa a caca e Iniciar retoma.
O movimento usa caminhos livres ate a posicao observada do lider, com passos
revalidados quando ele muda de celula. Todos os seguidores usam o mesmo nome,
mas cada um valida seu caminho no proprio cliente.

Nao precisa abrir porta de rede, compartilhar arquivos ou informar senhas de
outros jogadores. A coordenacao usa apenas o trafego que o proprio jogo ja envia.
Assim, exige lider visivel no mesmo mapa. Se ele sair da visao, ocultar ou mudar
de mapa, os seguidores aguardam; nao inventam coordenadas nem seguem teleportes
sem dados. Um canal entre bots seria outra etapa para coordenacao fora da visao.
Nomes duplicados/ambiguos nao sao escolhidos automaticamente. O alvo observado
vem de ataques/conjuracoes/danos recebidos, nao de leitura do cursor do outro PC.
O modo precisa ser validado em jogo com os membros apos atualizar e reconectar.
# Interface adaptavel

A roda do mouse apenas rola as paginas: numeros e seletores sao alterados por
clique, digitacao ou teclado. As cores de foco, selecao e botoes pressionados
destacam a acao atual. A ajuda das habilidades pode ser expandida sem sair da aba.

Os efeitos aprendidos ficam em `data/rede/buffs_aprendidos.json`, preservado nas
atualizacoes. A lista restaura esses vinculos mesmo ao reconstruir as habilidades;
desmarcar um buff desativa seu uso, mas nao apaga o aprendizado. Efeitos ativos sao
confirmados novamente pelos pacotes do servidor em cada conexao.

O painel usa navegacao lateral em janelas largas e abas com rolagem em janelas
menores. Em Configuracao, Navegacao, Grupo, Presenca e Atalhos ficam separados;
Monstros alvo passa para uma aba propria quando falta largura. Os formularios
rolam verticalmente em vez de comprimir os campos. Tabelas mantem rolagem
horizontal para suas colunas.

A pasta do jogo fica em Conexao. Iniciar, Pausar e Parar envios permanecem no
cabecalho. As configuracoes, atalhos e regras de aplicar/pausar continuam iguais.
Reabra o painel para carregar a nova interface; fechar o painel encerra a conexao
do jogo que estiver ligada a ele.

