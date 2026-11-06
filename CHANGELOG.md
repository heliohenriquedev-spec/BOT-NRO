# Changelog do BOT NRO

Novidades de cada atualização. O que ainda não foi publicado fica em "Próxima atualização".

## Próxima atualização

## 2026.11.06.8 (06/11/2026)

- Desempenho: o bot ficou mais leve durante a caça, o que reduz o lag no combate. Ele deixou de repetir a cada instante a checagem da conexão do jogo e as leituras dos arquivos da lista de observação e das opções da fila, e parou de calcular uma busca de monstros que não era usada. Também não reabre mais o arquivo de registro da caça a cada evento. Como os pacotes do servidor passam pelo bot antes de chegar ao jogo, isso deixa as respostas mais rápidas.
- Combate: se o bot manda habilidades ofensivas em um monstro por 1,5 s e nenhuma acerta, ele passa para outro monstro próximo e volta ao primeiro depois de 1 s. Se não houver outro monstro, continua no mesmo.
- Áreas de habilidade no chão (veneno e outras):
  - Um monstro em cima da área agora é atacado da célula ao lado, sem o bot pisar nela. Antes, o bot desistia do monstro por 8 s.
  - Se a área bloqueia o caminho até o alvo, o bot troca para outro monstro próximo que ele consiga alcançar e volta ao primeiro depois de 1 s. Faz no máximo uma troca a cada 3 s, para não ficar pulando entre monstros sem atacar. Se não houver outro alcançável, chega o mais perto que a área permite.
- Monstros dormindo, atordoados ou silenciados pelo bot voltam a ser atacados normalmente. Antes, como deixavam de mirar no personagem, saíam da lista de alvos do comportamento do mapa.
- Emergência dos Jounin (Selo de Mão: Coelho ×3 e Fukai Kemuri): se o servidor não confirma os Selos, o bot desiste da sequência e continua lutando, sem nova emergência por 30 s. Antes ele sempre acabava fugindo sem atacar. A fuga só acontece depois da Fukai Kemuri confirmada e dura no máximo 8 s.
- Limpeza: removidas três opções antigas de troca de alvo por distância, que ficavam escondidas no painel e não tinham efeito. Também saiu a busca de "último monstro visto", substituída pela patrulha e pelo @showmobs, e a linha "Memória do mapa" do painel.
- Comportamento do mapa: com o monstro colado e o ataque básico disponível, habilidades ofensivas com tempo de conjuração esperam, e o bot bate. Exemplo: TsuutenKyaku, ~1,3 s de conjuração. As habilidades instantâneas continuam na rajada.
- Jyuuken Ryuu (Ataque Duplo): o ataque básico que acerta duas vezes agora aparece na tela como um único golpe, com o mesmo dano, como já acontecia com as habilidades de vários acertos. Só muda o que o jogo desenha.

- @showmobs: agora todos os monstros encontrados contam. Antes só um era contado, e o bot ia atrás de um monstro sozinho ou desistia e passava a varrer o mapa em linha. Agora vai para onde há mais monstros juntos.
- Lista de observação: voltou a valer só na caça (patrulhando ou lutando). Nos percursos entre mapas, o bot não para nem alerta por jogadores da lista. Isso inclui fila de quests, caça pela database, volta depois de morrer, BG e teste de cura, além das tarefas da fila (montaria, equipamentos, @voltar).

## 2026.11.06.7 (06/11/2026)

- Caça: corrigido o personagem parado sem bater quando estava em cima de uma área de habilidade inimiga no chão. Os monstros ao redor eram tratados como se estivessem atrás de uma parede, e nenhum era atacado. Agora ele ataca normalmente, e as rotas continuam evitando a área.
- Lista de observação: com "Ativar observação" marcado, o bot para ao identificar um jogador da lista também durante os percursos e tarefas da fila de quests, não só na caça. Os outros jogadores continuam sem atrapalhar o percurso.

## 2026.11.06.6 (06/11/2026)

- Caça: corrigido o lag que atrasava as habilidades, fazia o personagem parar de bater e morrer mais. Nas caças da fila de quests e pela database, o bot reaplicava as configurações a cada meio segundo e reiniciava a caça; agora aplica uma vez só.
- Patrulha igual para todos: a forma de patrulhar do desenvolvedor passa a valer em todas as caças (comum, quests e database). Isso inclui espaçamento, cobertura, distância das paredes, raio, tempo para desistir e atacantes ignorados. Os monstros marcados para "usar @showmobs" também chegam a todos. Habilidades, alvos e o resto do combate continuam sendo de cada personagem.

## 2026.11.06.5 (06/11/2026)

- Caça com @showmobs: corrigido o personagem parado ("destravando" a cada 2 s) quando o ponto do @showmobs não tinha caminho; o ponto é deixado de lado por 45 s e a patrulha continua. Um monstro sozinho a mais de 60 células não vira mais destino.
- Patrulha: consultas de @showmobs agrupam alvos em janelas deslizantes de 50x50 celulas e priorizam o campo com maior concentracao; distancia desempata campos igualmente povoados.
- Patrulha: campos e waypoints permanecem estaveis durante a exploracao; sem dados de @showmobs, segue uma varredura linear e as consultas continuam em intervalos regulares.
- @showmobs: marcas ainda validas das consultas recentes sao agregadas; o foco persiste por mais tempo para alcancar alvos distantes.
- Navegacao: a patrulha percorre a coordenada marcada e reorienta o circuito ao chegar; evitar paredes tem prioridade sobre encurtar o trajeto.
- @showmobs: pequenas variacoes da marca dentro do mesmo grupo nao reiniciam o foco; ao chegar (ou desistir de um ponto sem progresso), a cobertura continua pela ordem do ciclo existente, sem inverter o trecho percorrido.
- Combate: alvos sem rota valida sao liberados e temporariamente adiados, mesmo quando atacam o personagem; isso evita travar a rotacao no mesmo alvo inalcançavel.
- Retorno apos morte: transferencias entre mapas aguardam a confirmacao de morte antes de acionar a protecao contra recall, permitindo que o fluxo de retorno e retomada da caca assuma.
- Patrulha: o recuperador de inatividade reordena somente os setores pendentes para priorizar os alcancaveis a partir da posicao atual, preservando o ciclo e limpando bloqueios temporarios que impediam novos movimentos.

- Combate: apos stun ou sono, o personagem se aproxima do Jounin ate o alcance da habilidade de silencio, mesmo enquanto ela aguarda recarga.
- Caca: monstros sob efeito de sono continuam como alvos elegiveis; regras de combate configuradas ainda podem exigir controle antes do dano.

## 2026.11.06.4 (06/11/2026)

- Caca pela database: consultas @showmobs repetem a cada 60 s e podem antecipar a busca apos 10 s sem alvo. Uma rodada sem resposta nao desativa novas consultas; tentativas antecipadas respeitam um intervalo minimo.
- Combate: confirmacoes de stun, sono e silencio nao contam como dano concluido. O controlador avalia os alvos visiveis dentro do raio antes de iniciar dano, e buffs com condicao de proximidade respeitam essa regra.
- Habilidades: recargas informadas pelo servidor prevalecem sobre atrasos temporarios de nova tentativa de buff.
- Rotas: caches de navegacao ficam associados ao mapa de colisao correto, evitando reaproveitar caminhos calculados para outro mapa.

- Caca pela database: ao chegar ao mapa de destino, as configuracoes de combate por mapa controlam alvos, prioridades e habilidades; a database continua controlando viagem e @showmobs. Se a montaria configurada nao estiver disponivel para o personagem, a rota segue a pe.
- Combate: uma habilidade pronta tem prioridade sobre o ataque basico; ataques basicos continuam intercalados nos intervalos entre habilidades.

## 2026.11.06.3 (06/11/2026)

- Combate: buffs de uso em si respeitam recargas informadas pelo servidor; recusas consecutivas aumentam a espera entre novas tentativas para evitar reenvios continuos.
- Navegação: a área prevista da Venom Dust agora usa a cruz de cinco células em vez de um quadrado maior.
- Comportamento por mapa: o motor permite aproximar de alvos elegíveis dentro de um raio limitado, sem perseguir além dele.

- Navegacao: duas opcoes independentes controlam evitar celulas de efeitos de terreno ja ativos e prever areas hostis quando a conjuracao comeca; ambos os bloqueios sao revalidados antes de enviar movimento.



- Rota de quests: configuracao para limitar de 1 a 20 tentativas de retorno ao ponto de salvamento enquanto o personagem permanece morto (padrao 4).


- Corrigida parada ao ver monstro inelegivel: a validacao de patrulha agora usa os mesmos alvos elegiveis do combate. Em area livre, adquire e aproxima de um alvo visivel; nao o descarta ao entrar no raio proximo. Atacantes a distancia continuam sendo defendidos. Regras de excecao do perfil nao bloqueiam a patrulha.
- Primeira ofensiva em alcance ganha o turno antes de renovacoes opcionais de buff, reduzindo o atraso para iniciar combate sem ignorar SP, recarga ou alcance. Adicionadas verificacoes de regressao para a selecao e a aproximacao de alvos.



- Perfis de combate agora aceitam prioridades de monstros, controle de stun/sono/silencio confirmado pelos pacotes, buffs persistentes e ofensivas intercaladas com ataques basicos, sem modificar a patrulha.

- Nova aba Comportamento por mapa: importa e exporta perfis JSON validados, aplica regras de combate por mapa, mantendo a patrulha normal e restaura as gerais ao sair. Perfis podem ser desativados e ficam suspensos durante quests.

- Morte na caça: nova opção (aba Rota de quests) para, ao morrer, voltar ao ponto de retorno, curar no NPC de cura e voltar ao mapa onde estava pelas rotas, na caça comum, na caça pela database e na fila de quests; a caça comum é retomada com as mesmas configurações. A conversa com o NPC de cura é gravada uma vez ("Gravar cura") e pode ser conferida com "Testar cura".
- BG e cura: estando já no mapa do NPC, o bot faz a conversa gravada (antes considerava a viagem concluída e não falava com ele).
- Combate: desligar o "Intercalar ataque básico" não liga mais o kite sozinho em configurações antigas; o kite só funciona com a opção de kite marcada.
- Caça pela database: opção "Usar @showmobs" por monstro (na janela de loot do monstro e na coluna @showmobs da janela "Caçar"); só os monstros marcados são procurados com @showmobs, e a escolha fica salva.
- @showmobs (caça pela database e quests): se não houver resposta ou nenhum grupo alcançável, o bot para de repetir o @showmobs naquele mapa e percorre o mapa inteiro em uma caminhada linear, como nos mapas de corredor. O @showmobs volta quando a caça ou a fila é iniciada de novo.

## 2026.11.06.2 (06/11/2026)

- Conexão: um NRO.exe de outra versão (por exemplo, atualizado pelo atualizador do jogo) é aceito quando a tabela de pacotes dele é idêntica à conhecida, conferida byte a byte; se a tabela mudou, o bot avisa e mostra o código da versão. A mensagem também diferencia "NRO.exe não encontrado na pasta escolhida".

## 2026.11.06.1 (06/11/2026)

- Portais: ao atravessar um portal, o bot registra para qual mapa ele leva; o portal mais próximo de onde você aparece fica registrado como a volta para o mapa anterior. Os destinos vão para todos na atualização.
- Rotas automáticas: cada portal em que você entra e cada NPC que troca de mapa (retorno no Kakashi, acesso e Sala VIP etc.) alimentam sozinhos o mapa de caminhos do bot, com a conversa e as opções escolhidas. A fila de quests, a entrada na BG e a caça pela database usam esses caminhos aprendidos junto com os percursos gravados; na janela "Caçar", esses mapas aparecem como "caminho aprendido pelos portais".
- BG: partindo de outro mapa, o bot vai até o NPC da BG e faz a conversa gravada (antes só chegava ao mapa).
- Portais: corrigido o registro automático das passagens entre mapas, que não gravava nenhum portal; agora vale também quando você clica longe e o personagem caminha até o portal. O arquivo data/mapas/portais_destinos.json é criado ao abrir o bot e recebe cada portal atravessado.
- Portais: um portal que leva a outro mapa deixa de ser tratado como portal interno (havia um falso no Kakashi, 52,2), assim que a passagem é confirmada.
- Database: novo botão "Caçar" na aba Monstros, na ficha de um monstro e na lista de quem dropa um item. Escolha o mapa, marque os monstros e a prioridade; o bot vai até lá pelo percurso gravado e caça com suas configurações de combate.
- Tela do jogo: removida a lista "Últimos registros de jogadores ocultos/fora de visão".
- Minimapa: NPCs aparecem como losangos ciano, com o nome ao passar o mouse; os nomes ficam salvos por mapa.
- Minimapa: coordenadas do personagem embaixo do minimapa, fixo ou solto.
- Minimapa: monstros encontrados pelo @showmobs aparecem como X rosa, com o nome ao passar o mouse.
- Minimapa: portais mostram o mapa de destino ao passar o mouse; jogadores escondidos ficam só com o marcador, sem texto.
- Caça: corrigido o travamento ao andar com o @showmobs (o nome de cada marca era lido do disco a cada atualização).
- Caça com @showmobs: o destino soma os monstros de todas as espécies consultadas e pesa o tamanho do grupo pela distância a pé até ele; um grupo distante só vence se for bem maior, e o destino só muda quando o novo é claramente melhor. Antes ia sempre para o maior grupo do mapa, atravessando o mapa de um lado para o outro.
- Caça pela database: metas por mortes, por minutos caçando no mapa ou por quantidade de um item juntado; termina na primeira atingida. Sem metas, caça até você parar.
- Caça pela database: sprite de cada monstro na janela "Caçar"; clicando, aparecem os loots com "Pegar este" (@alootid), "Pegar todos" e ligar/desligar @autoloot.
- BG: nova aba para entrar na BG 3x3, 4x4 ou 5x5. Grave o NPC de cada BG uma vez (andar, NPC e opções). As mensagens de erro e de sucesso são gravadas uma vez, em qualquer NPC, e valem para todas. Os botões "Entrar na 3x3", "4x4" e "5x5" falam com o NPC daquela BG e tentam de novo até a inscrição dar certo; aí param sozinhos.
- BG: botões "Gravar mensagem de erro" e "Gravar mensagem de sucesso": clique e fale com o NPC no jogo; a fala dele vira a mensagem usada para saber se a inscrição deu certo.
- Caça: "Ignorar até (atacando você)" agora conta só os monstros que não são alvo; os monstros caçados que revidam não fazem mais o bot atacar todos os outros.
- Minimapa e contador da quest: voltam a aceitar cliques e arraste com a Database, a janela Caçar ou outra janela do bot aberta.
- RCX: área da Ira de Thor (e das outras magias em área) aparece mesmo quando o servidor manda a unidade no chão antes do aviso da magia; antes ficava só um ponto.
- RCX: Pântano dos Mortos e as outras magias de área com unidade própria (Pneuma, Vulcão, Dilúvio, Gravidade etc.) mostram a área inteira quando o servidor manda só a unidade central.

## 2026.11.05.4 (05/11/2026)

- Notas de atualização: cada versão publicada passa a trazer a lista de novidades, também postada no canal de atualizações do Discord.
- RCX: pintura de habilidades no chao do jogo com canal direto de baixa latencia, cores, simbolos e opacidade personalizaveis por habilidade.
- RCX: previas de mira e conjuracao organizadas logo abaixo da aparencia do efeito, com ativacao independente e preferencias salvas imediatamente.
- RCX: suporte a habilidades de area usadas em si, como Desperado, e visualizacao configuravel da area de ativacao das armadilhas.
- RCX: tentativas de uso sem resposta nao deixam area temporaria; falhas e cancelamentos removem a previa correspondente.
- RCX: raio e formato ativam a personalizacao automaticamente; ID obtido da habilidade e bloqueado para edicao.
- RCX: preferencias preservadas entre paineis abertos, botao Salvar agora e confirmacao do arquivo utilizado.
- Quests: patrulha ativada na etapa de caca, retomada da exploracao apos destino sem progresso e observacao de jogadores suspensa durante os percursos.
- Quests: rotas concluidas comecam desmarcadas; ao marca-las novamente, e possivel repetir viagem e caca sem apagar o historico diario.
- Quests: corrigida a viagem isolada para usar os acessos compartilhados e conectar o mapa atual ao inicio do percurso, inclusive em outros personagens e computadores.
- Quests: editor otimizado com um indice de monstros carregado uma vez, evitando centenas de leituras repetidas da base.
- Atualizacao: confirmacao com espera minima de cinco segundos antes de baixar e reiniciar o painel.
- Quests: @showmobs soma os monstros dos tipos consultados, deduplica marcas e escolhe uma concentracao acessivel; a caca continua durante o trajeto.
- Changelog: registro das alteracoes pendentes revisado e orientacao do projeto para registrar cada pedido implementado antes da proxima publicacao.
- Database: todas as observacoes de monstros, mortes, itens, associacoes e drops do servidor passam a acompanhar as atualizacoes, com backup e mesclagem sem duplicar as coletas dos jogadores.
- Quests: isolamento dos testes corrigido para que gravacoes de validacao nunca usem o arquivo de rotas do usuario.
