; O aparelho mudo (#136) na ultima pagina do instalador, incluido no fim do ritmelli.iss. O "--microfone instala-todos"
; do [Run] grava o resultado em {tmp}\microfone.json (o --saida do microfone\microfone.py, em ASCII). Se a conferencia
; depois do reinicio do audio achou algum aparelho que abre e nao entrega som (a UMC 404HD da Behringer, ate tirar o
; cabo), a pagina de concluido diz qual e o que fazer, com a mesma frase do app (server.devices.silent). Em silencio (a
; atualizacao automatica e a pelo app), so o log do setup: o app confere de novo ao abrir e avisa na tela dele
; (engine.py). Num arquivo a parte para o dev\testa_aparelho_mudo.py montar um instalador so com ele.

[CustomMessages]
pt.Mudos=O Windows parou de receber som do dispositivo "%1". Desconecte o cabo USB dele e conecte novamente.
en.Mudos=Windows stopped receiving sound from the device "%1". Unplug its USB cable and plug it back in.

[Code]
var
  MudosLidos: Boolean;
  MudosAparelhos: String;

// os textos da lista Chave do JSON do microfone.py, juntos por '", "', como no aviso do app ('' sem a chave ou com a
// lista vazia). O JSON vem em ASCII: o \uXXXX volta a ser a letra
function MudosDoJson(Json, Chave: String): String;
var
  I, N: Integer;
  Dentro: Boolean;
  Item: String;
begin
  Result := '';
  I := Pos('"' + Chave + '"', Json);
  if I = 0 then
    Exit;
  I := I + Length(Chave) + 2;
  N := Length(Json);
  while (I <= N) and (Json[I] <> '[') do
    I := I + 1;
  I := I + 1;
  Dentro := False;
  Item := '';
  while I <= N do begin
    if not Dentro then begin
      if Json[I] = ']' then
        Break;
      if Json[I] = '"' then begin
        Dentro := True;
        Item := '';
      end;
    end else if Json[I] = '\' then begin
      I := I + 1;
      if I > N then
        Break;
      if Json[I] = 'u' then begin
        Item := Item + Chr(StrToIntDef('$' + Copy(Json, I + 1, 4), Ord('?')));
        I := I + 4;
      end else if (Json[I] = 'n') or (Json[I] = 'r') or (Json[I] = 't') then
        Item := Item + ' '
      else
        Item := Item + Json[I];  // \", \\ e \/
    end else if Json[I] = '"' then begin
      Dentro := False;
      if Result <> '' then
        Result := Result + '", "';
      Result := Result + Item;
    end else
      Item := Item + Json[I];
    I := I + 1;
  end;
end;

// o {tmp}\microfone.json, lido uma vez so e posto no log: os aparelhos mudos, ou ''
function MudosLe: String;
var
  Json: AnsiString;
begin
  if not MudosLidos then begin
    MudosLidos := True;
    if LoadStringFromFile(ExpandConstant('{tmp}\microfone.json'), Json) then begin
      MudosAparelhos := MudosDoJson(String(Json), 'aparelhos');
      if MudosAparelhos <> '' then
        Log('aparelhos mudos: "' + MudosAparelhos + '"')
      else
        Log('aparelhos: nenhum mudo');
    end else
      Log('aparelhos: sem o microfone.json');
  end;
  Result := MudosAparelhos;
end;

// a pagina de concluido: o aviso entra depois do texto do Ritmelli e antes do "Clique em Concluir", e a caixa de abrir
// o Ritmelli desce junto
<event('CurPageChanged')>
procedure MudosNaPagina(CurPageID: Integer);
var
  Aparelhos, Aviso, Texto: String;
  Folga, P: Integer;
begin
  if CurPageID <> wpFinished then
    Exit;
  Aparelhos := MudosLe;
  if Aparelhos = '' then
    Exit;
  Folga := WizardForm.RunList.Top - (WizardForm.FinishedLabel.Top + WizardForm.FinishedLabel.Height);
  Aviso := FmtMessage(CustomMessage('Mudos'), [Aparelhos]);
  Texto := WizardForm.FinishedLabel.Caption;
  P := Pos(SetupMessage(msgClickFinish), Texto);
  if P > 0 then
    Insert(Aviso + #13#10#13#10, Texto, P)
  else
    Texto := TrimRight(Texto) + #13#10#13#10 + Aviso;
  WizardForm.FinishedLabel.Caption := Texto;
  WizardForm.AdjustLabelHeight(WizardForm.FinishedLabel);
  WizardForm.RunList.Top := WizardForm.FinishedLabel.Top + WizardForm.FinishedLabel.Height + Folga;
end;

// em silencio a pagina nao aparece: o aviso fica no log
<event('CurStepChanged')>
procedure MudosNoLog(CurStep: TSetupStep);
begin
  if CurStep = ssDone then
    MudosLe;
end;
