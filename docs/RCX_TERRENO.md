# RCX / M2E no chão do NRO

A aba **RCX** desenha células de habilidades no chão do cliente NRO x86 validado.
Entre no personagem, aguarde carregar o mapa e clique em **Ativar RCX**.
**Desativar RCX** remove o desenho sem mudar o combate. `ABRIR_RCX.bat` abre o
mesmo controle independente do painel principal.

## Configurar uma habilidade

1. Busque pelo nome, código Ragnarok, ID da habilidade ou ID do efeito.
2. **Do personagem** filtra as habilidades aprendidas recebidas na conexão atual.
   **No mapa** mostra os tipos de efeito observados agora.
3. Selecione uma habilidade. Marque **RCX nas habilidades aliadas** e/ou **inimigas** e escolha as
   cores de preenchimento e traço, a opacidade e o símbolo. Há preenchimento,
   contorno, cruz, diagonal, losango e ponto central.
4. As alterações são gravadas imediatamente, mesmo com RCX desativado. O bot
   confirma o arquivo utilizado abaixo do editor. **Salvar agora** confirma valores
   ainda digitados nos campos. Uma falha ao aplicar o desenho não impede salvar.
   **Restaurar padrão deste efeito** desfaz a personalização selecionada.
   Dois painéis abertos preservam as edições um do outro; a gravação usa
   exclusão mútua entre processos e substituição atômica do arquivo.
   Em caso de falha, o aviso mostra o motivo e mantém as edições para tentar novamente.

O catálogo contém 146 habilidades e 130 tipos de unidade de terreno (0x7E–0xFF).
Os nomes recebidos do NRO substituem os nomes padrão quando disponíveis.
As entradas **efeito geral** configuram o tipo de unidade quando a habilidade
individual não foi identificada. Algumas magias compartilham o mesmo tipo de
unidade: a cor individual é usada quando o pacote permite identificar a magia;
sem essa evidência, é usado o estilo geral, sem adivinhar o conjurador/habilidade.

As preferências ficam em `data/rede/rcx_config.json`. Esse arquivo é protegido
contra substituição pelo atualizador. Catálogo, código e renderer são distribuídos
com a atualização; o usuário final não precisa instalar compilador ou RCX antigo.

## Prévia ao selecionar e conjurar a própria habilidade

- **Ao selecionar e mirar** acompanha a célula sob o cursor a cada quadro do jogo.
  Usa o estado de seleção do próprio cliente e a interseção do cursor com os
  triângulos e alturas reais do terreno. Sai ao cancelar a seleção, trocar de
  habilidade, perder o foco do jogo ou mudar de mapa.
- **Ao enviar / conjurar** mostra a área durante a barra informada pelo servidor.
  Um pedido enviado sem resposta não deixa pintura no chão. Falha ou cancelamento
  removem a prévia imediatamente; ela termina no prazo da barra, sem tempo extra.
  Habilidades instantâneas em si usam uma indicação breve após confirmação.
- A prévia tem cor, opacidade e símbolo próprios (inicialmente iguais aos do efeito).
  Não é uma confirmação de efeito ativo. Não é usada para mirar automaticamente
  nem altera alcance, consumo, delay, recarga ou comandos do personagem.
- Habilidades aprendidas com uso no chão recebem prévia sob o cursor.
  Habilidades de área usadas em si, como Desperado, recebem prévia na célula
  atual do personagem ao observar seu comando de uso ou confirmação do servidor.
  Habilidades instantâneas em si não possuem uma etapa de selecionar o chão. O modelo padrão
  considera o nível recebido quando o catálogo fornece tamanhos por nível.
- Para uma área customizada do NRO, marque **Personalizar área** e defina raio e
  formato. Raio 2 em quadrado significa 5×5 células. Raio 0 mostra só o centro.
  Alterar a aparência não troca o modelo de área automaticamente.
- **ID da habilidade (automático)** mostra o ID da entrada selecionada, sem
  permitir edição nem remapear uma habilidade para outra.
  Formatos especiais sem modelo conhecido usam apenas o centro até serem
  configurados; a prévia não promete reproduzir regras privadas do servidor.

## Células confirmadas e áreas Ragnarok

A captura acompanha unidades visíveis recebidas em 011F e remoções 0120.
Unidades sobrepostas são mantidas até a última remoção. O desenho acompanha a
câmera e as alturas atuais do terreno, respeitando o teste de profundidade.
Não é um minimapa nem mostra unidades que o servidor não enviou ao cliente.

Proteger Terreno, Santuário e demais unidades explícitas usam as células recebidas;
a configuração de raio da prévia não amplia essas células.

A exceção já existente são magias que anunciam uma área Ragnarok com unidade única
DUMMYSKILL (0x86). Chuva de Meteoros (83), Nevasca (89), Ira de Thor (Lord of
Vermilion, 85), Tempestade de Raios (Thunderstorm, 21) e Fúria da Terra (91) podem usar
esse tipo compartilhado. Só se associa uma área quando há anúncio
da mesma magia/conjurador em posição compatível (0117 ou 013E). Ela dura enquanto
a unidade existir. Sem anúncio compatível, mostra-se somente a unidade recebida.
O mesmo vale para magias de área com unidade própria do catálogo (Pântano dos Mortos/
Quagmire 0x8E, Pneuma, Vulcão, Dilúvio, Gravidade...): com o anúncio da magia, a área é
desenhada em volta da célula da magia, igual à que chegaria com todas as unidades. Santuário,
Proteção do Terreno e armadilhas continuam só com as células recebidas. O aviso da magia pode
chegar antes ou logo depois da unidade. Cada associação (ou falta dela) vai para
caca_eventos.jsonl como "rcx_area".
Essas áreas usam modelos Ragnarok, que podem diferir das customizações do NRO.

Fontes dos IDs e modelos padrão:
[rAthena skill.hpp](https://github.com/rathena/rathena/blob/master/src/map/skill.hpp)
e [skill_db pre-re](https://github.com/rathena/rathena/blob/master/db/pre-re/skill_db.yml).
O catálogo inclui a procedência; os modelos não são dados extraídos do servidor NRO.

## Latência e funcionamento

O relay publica os eventos em memória compartilhada local (`rcx_terreno.ipc`).
O controlador lê mudanças a cada 8 ms em uma thread independente do Qt e só
reconstrói os buffers quando os dados ou preferências mudam. A seleção do cursor
é resolvida no renderer a cada quadro, sem passar pelo temporizador do painel.
As alturas de terreno são reutilizadas entre quadros, com invalidação na troca de
mapa/base. Um heartbeat próprio limpa a pintura se o relay deixar de responder.
O arquivo JSON continua disponível como compatibilidade/diagnóstico.

Teste local sintético com 60 mudanças: mediana 8,60 ms, p95 9,32 ms e máximo 15,45 ms
entre publicação e buffer nativo. Isso **não mede** atraso de rede, escalonamento
sob outras cargas ou o próximo quadro Direct3D; não é garantia de latência no jogo.

O renderer aceita apenas os hashes de cliente/câmera validados em `rcx_client.py`,
confere a DLL pelo manifesto e integra o dispositivo Direct3D7 existente. Não envia
pacotes nem altera o NRO.exe no disco. Só um painel controla o RCX de cada cliente.
A DLL fica carregada sem desenhar após desativar, para não descarregar callbacks
em uso. Para carregar esta nova versão, reinicie jogo, painel e conexão uma vez.

## Validação

- Testes de configuração persistente, personalização individual, tipos
  compartilhados, prévia própria, expiração, troca de mapa e canal direto.
- `tools/validar_rcx_geometria.c`: 25.230 projeções/células verificadas em terreno
  sintético plano/inclinado, com três rotações e três inclinações de câmera.
- A interface foi renderizada e conferida localmente. A integração nativa anterior
  já foi confirmada visualmente no NRO pelo usuário; a nova prévia de seleção e
  os novos símbolos ainda precisam de confirmação visual em uma conjuração real.

O código e a licença GPL-3.0 do componente estão em `nrobot/native`; a compilação
reproduzível usa `tools/build_rcx.py` e Zig 0.13 para Windows x86. O estudo de
câmera/terreno usa como referência o
[SimpleROHook original](https://github.com/sekishi1259/SimpleROHook), não executa
nem exige seu pacote binário antigo.


## Desperado (GS_DESPERADO, 516)

O servidor do NRO informa Desperado como uso em si (tipo 4), com alcance de alvo 0.
O RCX usa a posição do personagem, não a do mouse. A prévia padrão é um
quadrado de raio 3 (7×7); **Personalizar área** permite alterar esse modelo.
O comando nativo 0072 e os usos do bot registram tentativas sem criar pintura
por conta própria. A resposta do servidor alimenta a prévia, sem enviar comandos adicionais. Pacotes de conjuração/dano podem confirmar a identificação, e uma
unidade de terreno compatível recebida do mesmo conjurador usa o estilo da habilidade.
A prévia sozinha não confirma dano nem efeito ativo.

As opções ficam em **Prévias desta habilidade**, logo abaixo de
**Aparência das células confirmadas**. A antiga opção de compartilhar cores
foi removida. Os controles de preenchimento, traço, símbolo e opacidade da prévia
começam iguais aos do efeito; continuam acompanhando essa aparência até você
personalizar cada campo da prévia. A personalização é independente e salva
por habilidade.

**Mostrar área enquanto escolho a célula no jogo** e **Mostrar durante a
conjuração confirmada** ativam/desativam as respectivas prévias somente para
a entrada selecionada. Os lados marcados (aliadas/inimigas) controlam separadamente o desenho
das unidades confirmadas. Desativar uma prévia não muda as outras habilidades.
Salvar aplica sem reiniciar; reabra o painel uma vez para carregar esta reorganização.

### Editar raio e formato

Os campos ficam sempre editáveis. Alterar **Raio** ou **Formato** marca
**Personalizar área** automaticamente, salva e aplica a prévia. Desmarcar a
opção restaura o modelo/raio padrão da habilidade e do nível recebido.
Exemplo: raio 5 em quadrado desenha uma prévia de 11×11 células.
Isso modifica a prévia visual; não muda o alcance real nem amplia as unidades
confirmadas pelo servidor.


### Antes de clicar no chão (mira da habilidade)

Com RCX ativo, habilite **Mostrar área enquanto escolho a célula no jogo**.
Selecione Instalar Armadilha ou outra habilidade de chão e mova o mouse sem clicar:
a prévia acompanha a célula apontada, seguindo a câmera a cada quadro. Não precisa
iniciar a caça nem enviar uma conjuração para aparecer. Cancelar a seleção oculta
a mira; ao conjurar, a prévia de conjuração segue sua opção independente.

Instalar Armadilha (117) usa, por padrão, uma prévia de ativação 3×3
(Unit.Range 1 do modelo Ragnarok), não apenas a célula de instalação.
Isso é um modelo visual ajustável para as regras do NRO, não confirma que uma
armadilha foi colocada. Aumentar o raio de um formato **Somente centro** troca-o
para **Quadrado** automaticamente; ainda é possível escolher outro formato depois.


## Tentativas sem sucesso, cancelamento e IDs automáticos

Enviar um pedido de habilidade não pinta mais uma área temporária. O pedido é
registrado separadamente e não vira uma conjuração visual por timeout.
A mira ainda acompanha o cursor enquanto o cliente estiver selecionando uma
célula. Depois do clique, a barra de conjuração informada pelo servidor pode
mostrar a prévia apenas durante sua duração; não há mais meio segundo extra.
Falha de uso (0110), cancelamento do conjurador (01B9), conclusão ou troca de
mapa limpam a prévia correspondente. Uma habilidade instantânea em si, como
Desperado, só gera marcação breve após resposta de execução/dano do servidor.
Unidades reais recebidas continuam até o servidor removê-las.

O campo **ID da habilidade (automático)** é somente leitura. Instalar Armadilha
usa 117; Desperado usa 516. Entradas de efeito geral podem corresponder a várias
habilidades e mostram essa indicação. Remapeamentos manuais antigos são
ignorados; as cores e os tamanhos permanecem associados à entrada selecionada.

O modelo de ativação da armadilha instalada também usa o raio/formato da
configuração, sem alterar as regras do servidor: padrão raio 1/quadrado =
9 células (3×3). O editor informa o total e as dimensões para evitar confundir
raio com largura. Trata-se da visualização modelada de ativação, distinta das
coordenadas de instalação explicitamente recebidas.

Referência de confirmação/cancelamento: [rAthena clif.cpp](https://github.com/rathena/rathena/blob/master/src/map/clif.cpp),
funções clif_skillcasting, clif_skillcastcancel e clif_skill_fail.

### Conjurações de outros personagens

O início de conjuração recebido do servidor também pode mostrar a área de outros
conjuradores, sem exigir que seu personagem tenha a habilidade aprendida. A prévia
usa a célula anunciada, o catálogo e a personalização da habilidade; não transforma
essa estimativa em células de efeito confirmado. Cancelamento e fim do cast removem
a prévia daquele conjurador, sem apagar casts simultâneos de outras pessoas.

Cada habilidade tem **Mostrar habilidades aliadas** e **Mostrar habilidades inimigas**,
ambas ligadas por padrão. Valem para as prévias e as células recebidas. São aliados
o grupo configurado, suas invocações e personagens da mesma PT/clã quando esses
dados estão disponíveis nos pacotes. Demais fontes usam o filtro de inimigos para
exibição. Suas proprias habilidades tambem usam o filtro de aliadas, incluindo as previas de selecao, conjuracao e os efeitos confirmados. Desmarcar um lado no efeito geral oculta esse lado para todas as habilidades daquele efeito, mesmo com estilos individuais salvos.

Regra de aliado/inimigo (`nrobot/rcx_sides.py`), decidida por pacotes do servidor:

- **Mapa sem PvP:** todos os jogadores sao aliados (o Santuario de qualquer um cura voce).
- **Mapa PvP** (propriedade de mapa 0199 com PvP/GdE, ou ranking PvP 019A no mapa atual):
  aliados sao o grupo configurado, a PT (00FB/0104/0105) e a mesma guilda.
- **BG:** o servidor informa a equipe de cada personagem (02DD) ao entrar no mapa e quando
  alguem aparece. So a sua equipe e aliada; a vila e ignorada ali.
- **Invocacoes:** uma criatura criada ate 8 celulas de um jogador nos 3 s apos uma habilidade
  de invocacao conhecida pelo bot segue o lado desse jogador. As suas seguem a deteccao propria.
- **Monstros** sao inimigos. O rank exibido depois do nome (campo de PT no NRO) nunca conta.

A troca de mapa volta para "sem PvP" e descarta equipes e donos de invocacoes. Cada pacote de
propriedade de mapa recebido fica em caca_eventos.jsonl como "rcx_map_side".

## Ocultar o efeito original do jogo

Nao ha mais **Mostrar este efeito**: o RCX age numa habilidade apenas para os lados marcados
em **RCX nas habilidades aliadas** (inclui as suas e as previas) e **RCX nas habilidades
inimigas**. Nenhum marcado: o RCX nao age e o jogo mostra o efeito normal. Todas as entradas
comecam desmarcadas. Um lado marcado no efeito geral vale para todas as habilidades do tipo.
Arquivos anteriores (sem `sides_version` 2) sao convertidos uma vez: entradas com os dois lados
ligados (o padrao antigo) ou com o efeito desligado ficam sem lados; os ajustes feitos pelo
usuario permanecem. Uma copia do arquivo anterior fica em `rcx_config.json.antes_lados`.

Cada entrada tem **Ocultar o efeito original do jogo (fica so o desenho do RCX)**, desligada
por padrao. Ligada, e com o RCX desenhando no jogo, o relay deixa de repassar ao cliente a
unidade no chao (011F) e a animacao da magia no local (0117) dessa habilidade. O bot continua
lendo os pacotes originais, entao as celulas do RCX, a esquiva e o combate nao mudam.

- So oculta no lado em que o RCX age: com apenas inimigas marcado, o efeito some nas
  habilidades inimigas e continua no jogo para as aliadas.
- Uma habilidade sem estilo proprio segue a opcao do efeito geral; marcada ou desmarcada
  na habilidade, vale a da habilidade.
- O painel do RCX renova o arquivo `rcx_ativo` na pasta da conexao enquanto desenha. Sem
  ele (RCX desativado, painel fechado) nada e ocultado. Unidades ja ocultadas continuam
  invisiveis no cliente ate o servidor remove-las; as novas voltam a aparecer.
- Altera so o que o cliente desenha. Nao muda dano, duracao nem o que o servidor aplica.


## Visao local de ocultos

A opcao "Visao local de ocultos (Byakugan)" aplica ao cliente o efeito visual observado no teste com o item, sem equipar o item nem alterar atributos no servidor. E independente do RCX de terreno e vale para os personagens conectados pelo relay neste computador. A disponibilidade visual ainda precisa ser conferida no jogo; entidades que o servidor nao envia nao podem ser reveladas.

Apos instalar esta alteracao, reabra o painel e reconecte o personagem para carregar o novo relay. Depois, o controle pode ser ligado ou desligado na aba RCX sem reiniciar. A sombra vermelha antiga de hide foi retirada; o minimapa e os alertas permanecem.

O estado `client_vision` em `estado.json` registra o ID do jogador usado no mapa, se o cliente esta pronto, o efeito visual encaminhado e possiveis erros de enquadramento. Esse ID vem da conta; o ID da selecao do personagem nao identifica o ator no mapa. Os registros originais do servidor continuam separados da alteracao visual local.
