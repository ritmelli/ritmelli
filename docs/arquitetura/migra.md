# A troca de nome de Vitrola para Ritmelli (`migra.py`)

`migra.py`: a troca de nome de Vitrola para Ritmelli (#58) no PC de quem já tinha o app, pelo
instalador, como administrador. O `--migra maquina` vem antes do filtro de microfone: copia o
`HKLM\SOFTWARE\Vitrola` para o `HKLM\SOFTWARE\Ritmelli` sem trocar o que o novo já tem (a escolha
dos dados de uso, o original de cada microfone e as vagas do hospedeiro: sem eles o filtro
guardaria a si mesmo como original) e apaga as tarefas de antes (o `schtasks` e o `powershell`
pelo caminho completo da System32, o `pastas.do_windows`). O `vitrola.exe` aberto o setup já
fechou, pelo caminho completo, no `PrepareToInstall` (`instalador\encerra.ps1`). O
`--migra limpa` vem no fim, com o áudio já reiniciado na DLL nova: apaga o registro de antes e
a pasta padrão de antes (`Program Files\Vitrola`), e o que estiver preso sai no reinício. A limpeza
dessa pasta (`pasta_velha`, que também roda em toda rodada da tarefa de atualização, como SYSTEM)
só mexe nela se ela passa na regra da pasta protegida (`migra.PROTEGIDA`) e não contém o app que
está rodando; senão, só o motivo vai para o log. O `ritmelli.iss` leva a instalação de
`Program Files\Vitrola` para `Program Files\Ritmelli`, e a parcial não serve por cima de uma versão
de antes (o `parcial.py` não a gera). O nome do app no
manifesto continua `vitrola` (o `APP` do `publica.py`): a 0.4.1 e o Ritmelli até a 0.6.0 só aceitam
esse. As versões depois delas aceitam também `ritmelli` (o `APPS` do `atualizacao.py`), e o manifesto
só pode trocar quando nenhuma versão que ainda deve atualizar conferir só o de antes. O celular
pareado antes segue pelo cookie de antes (`pareamento.chave_do`), e o modo de cada pedal, pela
chave de antes no `localStorage`.
