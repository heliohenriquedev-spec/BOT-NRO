# RCX / M2E no chão do NRO

A aba **RCX** desenha células de habilidades no chão do cliente NRO x86 validado.
Entre no personagem, aguarde carregar o mapa e clique em **Ativar RCX**.
**Desativar RCX** remove o desenho sem mudar o combate. `ABRIR_RCX.bat` abre o
mesmo controle independente do painel principal.

## Configurar uma habilidade

1. Busque pelo nome, código Ragnarok, ID da habilidade ou ID do efeito.
2. **Do personagem** filtra as habilidades aprendidas recebidas na conexão atual.
   **No mapa** mostra os tipos de efeito observados agora.
3. Selecione uma habilidade. Ative/desative **Mostrar este efeito** e escolha as
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
DUMMYSKILL (0x86). Chuva de Meteoros, Nevasca, Lorde dos Kaos, Ira de Thor e Fúria da
Terra podem usar esse tipo compartilhado. Só se associa uma área quando há anúncio
da mesma magia/conjurador em posição compatível (0117 ou 013E). Ela dura enquanto
a unidade existir. Sem anúncio compatível, mostra-se somente a unidade recebida.
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
a entrada selecionada. **Mostrar este efeito** controla separadamente o desenho
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
