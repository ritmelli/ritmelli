; O aparelho mudo (#136) na ultima pagina do instalador, incluido no fim do ritmelli.iss. O "--microfone instala-todos"
; do [Run] grava o resultado em {tmp}\microfone.json (o --saida do microfone\microfone.py, em ASCII). Se a conferencia
; depois do reinicio do audio achou algum aparelho que abre e nao entrega som (a UMC 404HD da Behringer, ate tirar o
; cabo), a pagina de concluido diz qual e o que fazer, com a mesma frase do app (server.devices.silent). O resumo da
; conferencia (quantos aparelhos, os mudos, os que nao abriram, ou por que nao conferiu) vai para o log do setup: o
; ritmelli.exe nao tem console. Em silencio (a atualizacao automatica e a pelo app), so o log: o app confere de novo ao
; abrir e avisa na tela dele (engine.py). Num arquivo a parte para o dev\testa_aparelho_mudo.py montar um instalador so
; com ele.

[CustomMessages]
pt.Mudos=O Windows parou de receber som do dispositivo "%1". Desconecte o cabo USB dele e conecte novamente.
en.Mudos=Windows stopped receiving sound from the device "%1". Unplug its USB cable and plug it back in.

[Code]
var
  MudosLidos: Boolean;
  MudosAparelhos: String;

// o texto JSON que comeca na aspa em Json[I], sem as aspas e com os escapes desfeitos: o \uXXXX volta a ser a letra (o
// JSON vem em ASCII), e o \b, \f, \n, \r e \t viram espaco. I termina depois da aspa do fim
function MudosLeTexto(Json: String; var I: Integer): String;
var
  N: Integer;
begin
  Result := '';
  N := Length(Json);
  I := I + 1;
  while I <= N do begin
    if Json[I] = '"' then begin
      I := I + 1;
      Exit;
    end;
    if Json[I] = '\' then begin
      I := I + 1;
      if I > N then
        Exit;
      if Json[I] = 'u' then begin
        Result := Result + Chr(StrToIntDef('$' + Copy(Json, I + 1, 4), Ord('?')));
        I := I + 4;
      end else if Pos(Copy(Json, I, 1), 'bfnrt') > 0 then
        Result := Result + ' '
      else
        Result := Result + Json[I];  // \", \\ e \/
    end else
      Result := Result + Json[I];
    I := I + 1;
  end;
end;

// onde comeca o valor da Chave do JSON (depois dos dois pontos e dos espacos), ou 0 sem a chave
function MudosValor(Json, Chave: String): Integer;
begin
  // com os dois pontos: dentro de um texto do JSON, a aspa vem escapada, e o nome de um aparelho nao casa
  Result := Pos('"' + Chave + '":', Json);
  if Result = 0 then
    Exit;
  Result := Result + Length(Chave) + 3;
  while (Result <= Length(Json)) and (Json[Result] = ' ') do
    Result := Result + 1;
end;

// o texto da Chave do JSON do microfone.py ('' sem a chave)
function MudosTextoDoJson(Json, Chave: String): String;
var
  I: Integer;
begin
  Result := '';
  I := MudosValor(Json, Chave);
  if (I > 0) and (I <= Length(Json)) and (Json[I] = '"') then
    Result := MudosLeTexto(Json, I);
end;

// os textos da lista Chave do JSON do microfone.py, juntos por '", "', como no aviso do app ('' sem a chave ou com a
// lista vazia)
function MudosDoJson(Json, Chave: String): String;
var
  I, N: Integer;
  Item: String;
begin
  Result := '';
  I := MudosValor(Json, Chave);
  N := Length(Json);
  if (I = 0) or (I > N) or (Json[I] <> '[') then
    Exit;
  I := I + 1;
  while (I <= N) and (Json[I] <> ']') do begin
    if Json[I] = '"' then begin
      Item := MudosLeTexto(Json, I);
      if Result <> '' then
        Result := Result + '", "';
      Result := Result + Item;
    end else
      I := I + 1;
  end;
end;

// o {tmp}\microfone.json, lido uma vez so e posto no log: o resumo da conferencia e os aparelhos mudos, ou ''
function MudosLe: String;
var
  Json: AnsiString;
  Resumo: String;
begin
  if not MudosLidos then begin
    MudosLidos := True;
    if LoadStringFromFile(ExpandConstant('{tmp}\microfone.json'), Json) then begin
      Resumo := MudosTextoDoJson(String(Json), 'conferencia');
      if Resumo = '' then
        Resumo := 'sem conferencia (o audio nao reiniciou, ou o microfone.py parou antes)';
      Log('aparelhos: ' + Resumo);
      MudosAparelhos := MudosDoJson(String(Json), 'aparelhos');
      if MudosAparelhos <> '' then
        Log('aparelhos mudos: "' + MudosAparelhos + '"');
    end else
      Log('aparelhos: sem o microfone.json');
  end;
  Result := MudosAparelhos;
end;

// a pagina de concluido: o aviso entra depois do texto do Ritmelli e antes do "Clique em Concluir", e a caixa de abrir
// o Ritmelli desce junto (ou, quando o Windows pede para reiniciar, as duas opcoes de reiniciar agora ou depois)
<event('CurPageChanged')>
procedure MudosNaPagina(CurPageID: Integer);
var
  Aparelhos, Aviso, Texto: String;
  Antes, Desce, P: Integer;
begin
  if CurPageID <> wpFinished then
    Exit;
  Aparelhos := MudosLe;
  if Aparelhos = '' then
    Exit;
  Antes := WizardForm.FinishedLabel.Top + WizardForm.FinishedLabel.Height;
  Aviso := FmtMessage(CustomMessage('Mudos'), [Aparelhos]);
  Texto := WizardForm.FinishedLabel.Caption;
  P := Pos(SetupMessage(msgClickFinish), Texto);
  if P > 0 then
    Insert(Aviso + #13#10#13#10, Texto, P)
  else
    Texto := TrimRight(Texto) + #13#10#13#10 + Aviso;
  WizardForm.FinishedLabel.Caption := Texto;
  WizardForm.AdjustLabelHeight(WizardForm.FinishedLabel);
  Desce := WizardForm.FinishedLabel.Top + WizardForm.FinishedLabel.Height - Antes;
  WizardForm.RunList.Top := WizardForm.RunList.Top + Desce;
  WizardForm.YesRadio.Top := WizardForm.YesRadio.Top + Desce;
  WizardForm.NoRadio.Top := WizardForm.NoRadio.Top + Desce;
end;

// em silencio a pagina nao aparece: o aviso fica no log
<event('CurStepChanged')>
procedure MudosNoLog(CurStep: TSetupStep);
begin
  if CurStep = ssDone then
    MudosLe;
end;
