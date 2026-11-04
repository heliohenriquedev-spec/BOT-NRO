# Login automático por telas e pacotes

## Conferido localmente

`C:\NRO - Jogo COMPLETO` contém o executável e os recursos do cliente, não o
código-fonte do servidor. A tabela do cliente verificada pelo hash do NRO.exe
informa os comprimentos 0064=55, 0065=17 e 0066=3. O formato clássico é compatível
com as estruturas públicas PACKET_CA_LOGIN e PACKET_CH_SELECT_CHAR do rAthena:
https://github.com/rathena/rathena/blob/master/src/common/packets.hpp

O cliente precisa iniciar a própria conexão antes de receber a autenticação.
O controlador usa somente o texto fictício `nrobotinit` nos campos da janela para
gerar esse pedido. O relay substitui esses dados pela conta e senha configuradas
no pacote reconhecido. Credenciais reais nunca são digitadas na janela do jogo.

## Implementado e testado

- Credenciais protegidas por DPAPI continuam locais e não são distribuídas.
- Ao receber um pedido nativo 0064 reconhecido e com tamanho validado, o relay
  substitui apenas os campos da conta e senha pelos dados configurados. Preserva
  versão, tipo do cliente e mensagens anexadas. Lida com fragmentação TCP.
- No login manual, formatos desconhecidos passam sem alteração. Na inicialização
  automática, formato desconhecido, senha inválida ou pausa interrompem a tentativa
  antes de encaminhar dados fictícios. Dados incompatíveis não são truncados nem
  aparecem em diagnósticos. Não se salva tráfego de login.
- O bot não digita mais credenciais nem pressiona Enter baseado em espera fixa.
- A seleção automática do personagem continua por nome na lista do servidor,
  com verificação da conexão/etapa e cancelamento ao avançar para o mapa. Uma
  seleção manual recebida antes da automática tem precedência.
- Os testes isolam o arquivo de configuração do login para não sobrescrever os
  dados salvos pelo usuário.
- Imagens de referência do próprio cliente são distribuídas em `data/recursos/login`.
  A detecção encontra a janela e o botão em posições/escalas diferentes. Não depende
  da pasta privada de GRFs descriptografadas.
- O aviso de desconexão só é confirmado quando o estado do relay também indica
  desconexão. Avisos desconhecidos e recusas de login exigem controle manual.
- A conexão BOT LOCAL é identificada no XML do perfil instalado pelo endereço e
  porta locais. O mundo desejado (ex.: NRO(50)) é definido pela lista recebida:
  o relay apresenta somente o mundo configurado ao cliente e a interface confirma.
- A tela de personagens não recebe cliques nos retratos: o relay escolhe pelo nome.
- Uma tela precisa permanecer estável antes de qualquer ação. O jogo precisa estar
  em primeiro plano. Perder foco ou pausar interrompe a entrada de dados fictícios.
  Não há repetição cega de Enter nem tentativas infinitas de autenticação.

## Como utilizar

1. Reabra o painel atualizado e salve conta, senha e nome exato do personagem.
2. Ative o login automático e a opção de avançar pelas telas reconhecidas.
3. Escolha o número do mundo na lista após a autenticação (normalmente 1 para NRO(50)).
   A conexão BOT LOCAL da primeira lista é localizada automaticamente pelo perfil.
4. Abra a conexão no painel e deixe a janela do jogo em primeiro plano.
5. Use Pausar/Retomar login automático quando quiser navegar manualmente.

Se já estiver no formulário de login sem o relay confirmar a conexão local, volte
à seleção de conexão para que o controlador escolha BOT LOCAL. Uma skin diferente,
formato de pacote não suportado, resposta negativa ou tela que não avança deixam
o fluxo parado/pausado com diagnóstico. Confira o motivo antes de retomar.

O fluxo foi testado com telas compostas dos recursos do cliente em diferentes
posições/escalas e servidores de teste locais. A autenticação real da conta e a
entrada de mouse/teclado na sessão aberta ainda precisam ser validadas no jogo.

### Pausar para capturar as telas

No grupo Login automático, o botão **Pausar login automatico** salva uma pausa
independente da caça e da conexão. Cancela escolhas de personagem ainda pendentes
e deixa o login manual disponível. O botão passa a **Retomar login automatico**.
A pausa continua após fechar/reabrir o painel e não apaga conta, senha ou personagem.
Uma escolha que já chegou ao servidor não pode ser desfeita pela pausa.

Para capturar a seleção de personagem, abra a versão atualizada do painel,
pause o login antes de abrir a conexão e avance manualmente pelas telas.
Não é preciso encerrar o relay para acionar o botão depois disso.

As cinco telas enviadas foram usadas como referência para a sequência. Não foram
adicionadas injeção no processo, alterações no executável ou autenticação por uma
conexão externa que não pertença ao cliente aberto.

## @hide no NRO

Inspecionar os recursos e o executável local não fornece a lógica de visibilidade
do servidor. O bot pode acompanhar apenas os sinais que chegam à conexão e a
última posição conhecida. Nenhuma detecção nova de GM foi implementada. Para
confirmar particularidades do NRO, é necessária uma captura controlada com um
administrador ou acesso autorizado ao código/API do servidor.
