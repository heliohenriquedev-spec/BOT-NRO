# Changelog do BOT NRO

Novidades de cada atualização. O que ainda não foi publicado fica em "Próxima atualização".

## Próxima atualização

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
