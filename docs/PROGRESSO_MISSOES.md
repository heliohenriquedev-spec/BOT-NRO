# Progresso e histórico das missões

As mortes contadas, os contadores por espécie e por nome, a rota atual, a etapa, as missões já pegadas/entregues e o contexto das rotas encadeadas são salvos a cada mudança. Fechar normalmente o relay também força um último salvamento. Não é necessário aguardar três segundos após uma morte para salvar.

Depois de reiniciar, entre no mesmo personagem e use **Rota de quests → Retomar fila**. O resumo do progresso salvo aparece nessa aba. O bot recupera os contadores e segue pela rota apropriada ao mapa atual; ele não retoma automaticamente o envio de comandos ao abrir. Contagens são observações do bot, não uma consulta retroativa ao servidor: mortes ocorridas com o bot desligado não podem ser reconstruídas.

**Iniciar nova fila** inicia outra execução do zero. Se houver progresso salvo, o painel pede confirmação antes de substituí-lo. O histórico anterior continua disponível mesmo ao iniciar outra execução ou concluir a fila. Concluir a fila remove o ponto de retomada e sua cópia, para não ressuscitar uma execução terminada.

Arquivos locais, preservados pelo atualizador e não publicados:

- `data/rede/progresso_quests.json`: último ponto de retomada salvo.
- `data/rede/progresso_quests.json.bak`: versão anterior válida; usada automaticamente se o arquivo principal estiver ausente ou ilegível. Nesse caso, o ponto recuperado pode ser anterior à última mudança.
- `logs/progresso_quests.log`: histórico permanente de mudanças, sem exclusão automática na virada do dia, inclusive contagens. Registros já apagados por versões anteriores não são reconstruídos.

A gravação do ponto de retomada usa arquivo temporário, sincronização em disco e substituição atômica. Uma falha de gravação é informada no diagnóstico e o bot tenta novamente nas mudanças seguintes; não há garantia de persistência se o disco não permitir gravar. Quando o personagem foi identificado ao salvar, a retomada impede aplicar seus contadores a outro personagem.
