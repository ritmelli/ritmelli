# A troca de nome de Vitrola para Ritmelli (`migra.py`)

`migra.py`: a troca de nome de Vitrola para Ritmelli (#58) no PC de quem já tinha o app, pelo
instalador, como administrador. O `--migra maquina` vem antes do filtro de microfone: fecha o
`vitrola.exe`, copia o `HKLM\SOFTWARE\Vitrola` para o `HKLM\SOFTWARE\Ritmelli` sem trocar o que o
novo já tem (a escolha dos dados de uso, o original de cada microfone e as vagas do hospedeiro:
sem eles o filtro guardaria a si mesmo como original) e apaga as tarefas de antes. O
`--migra limpa` vem no fim, com o áudio já reiniciado na DLL nova: apaga o registro de antes e
a pasta padrão de antes (`Program Files\Vitrola`), e o que estiver preso sai no reinício. O
`ritmelli.iss` muda a pasta padrão para `Program Files\Ritmelli` (a escolhida à mão fica), e a
parcial não serve por cima de uma versão de antes (o `parcial.py` não a gera). O nome do app no
manifesto continua `vitrola` (o `APP` do `publica.py`): a 0.4.1 e o Ritmelli até a 0.6.0 só aceitam
esse. As versões depois delas aceitam também `ritmelli` (o `APPS` do `atualizacao.py`), e o manifesto
só pode trocar quando nenhuma versão que ainda deve atualizar conferir só o de antes. O celular
pareado antes segue pelo cookie de antes (`pareamento.chave_do`), e o modo de cada pedal, pela
chave de antes no `localStorage`.
