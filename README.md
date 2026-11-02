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
