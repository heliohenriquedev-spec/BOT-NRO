# Recuperação do homúnculo

As rotinas de alimentação e recuperação só funcionam em personagens com pelo menos uma das habilidades aprendidas: Invocar Marionete (243), Vaporizar (244) ou Remontar Marionete (247). Cada comando também exige que sua habilidade específica esteja aprendida. Para guardar e trazer de volta, são necessárias tanto Vaporizar quanto Invocar.

A regra de 8 células foi removida. O bot usa a remoção da entidade informada pelo servidor para reconhecer a saída da visão. Uma posição distante ou o destino de uma caminhada não autorizam Vaporizar. Isso corresponde à visão de entidades recebida pela conexão; não é uma medição dos pixels da janela ou do zoom da câmera. Os arquivos locais incluem scripts Lua da IA, mas não o código-fonte completo do servidor/cliente que define essa área.

Após 3 segundos fora dessa visão, o bot tenta Vaporizar e depois Invocar. O envio de Invocar não confirma o reaparecimento: a recuperação só termina ao receber aparição ou posição/movimento do próprio homúnculo. Sem resposta, são feitas até três tentativas de Invocar, seguidas de uma espera de 15 segundos antes de repetir a recuperação. Morte observada dá prioridade a Remontar Marionete. As tentativas respeitam recarga do servidor, conjuração, intervalo global e SP conhecido.

No ciclo de caça, uma ação disponível para recuperar o homúnculo é enviada antes da fila de invocações e das ofensivas. Movimentação continua permitida; ausência de habilidade, recarga ou falta de confirmação não bloqueiam indefinidamente a caça. Controle manual, presença que suspende a caça e modo de grupo apenas seguir impedem a recuperação automática de combate. O alvo atacado pelo homúnculo não muda o alvo escolhido pelo personagem nem obriga esperar uma morte fora da quest.

Reabra o painel e a conexão para carregar as alterações. Validações automatizadas simulam pacotes e transportes; não confirmam o resultado de uma sessão real do jogo.
