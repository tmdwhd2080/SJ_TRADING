Option Explicit

Private Const USE_EOM_CONVENTION As Boolean = True
Private Const INCLUDE_KRX_YEAR_END_CLOSE As Boolean = False
Private Const KRX_LOOKAHEAD_YEARS As Long = 5

Private Const INPUT_HEADER_ROW As Long = 2
Private Const INPUT_VALUE_ROW As Long = 3
Private Const INPUT_FIRST_COL As Long = 4
Private Const OUTPUT_HEADER_ROW As Long = 8
Private Const OUTPUT_FIRST_ROW As Long = 9
Private Const MAX_QUARTERS As Long = 80
Private Const REFRESH_BUTTON_NAME As String = "btnRefreshIRSCurve"
Private Const RATE_FORMAT As String = "0.0000000000"
Private Const DATE_FORMAT As String = "yyyy-mm-dd"

Public Sub RefreshIRSCurve()
    On Error GoTo Fail

    Dim ws As Worksheet
    Set ws = ActiveSheet

    Application.ScreenUpdating = False
    Application.EnableEvents = False

    SetupIRSCurveSheet ws

    If IsDate(ws.Cells(INPUT_VALUE_ROW, INPUT_FIRST_COL).Value) = False Then
        MsgBox "D3에 기준일을 입력하세요.", vbExclamation
        GoTo CleanExit
    End If

    Dim tradeDate As Date
    tradeDate = CDate(ws.Cells(INPUT_VALUE_ROW, INPUT_FIRST_COL).Value)

    Dim keyMonths As Variant
    keyMonths = KeyTenorMonths()

    Dim keyRates As Object
    Set keyRates = CreateObject("Scripting.Dictionary")

    Dim i As Long
    Dim inputCol As Long
    For i = LBound(keyMonths) To UBound(keyMonths)
        inputCol = INPUT_FIRST_COL + 1 + i
        If Not IsNumeric(ws.Cells(INPUT_VALUE_ROW, inputCol).Value) Then
            MsgBox ws.Cells(INPUT_HEADER_ROW, inputCol).Value & " 금리를 숫자로 입력하세요.", vbExclamation
            GoTo CleanExit
        End If
        keyRates(CStr(keyMonths(i))) = CDbl(ws.Cells(INPUT_VALUE_ROW, inputCol).Value)
    Next i

    Dim holidays As Object
    Set holidays = CreateObject("Scripting.Dictionary")
    UpdateIrsCalendar holidays, Year(tradeDate), Year(DateAdd("yyyy", 21, tradeDate))
    ws.Activate

    Dim effectiveDate As Date
    effectiveDate = AddBusinessDays(tradeDate, 1, holidays)

    Dim useEom As Boolean
    useEom = USE_EOM_CONVENTION And IsBusinessMonthEnd(effectiveDate, holidays)

    ws.Range("A8:H250").Clear
    ws.Range("A8:H8").Value = Array("TENOR", "날짜", "IRS", "할인일수", "보간 IRS", "사이일(계산 편의용)", "DF", "ZCR")

    Dim rowByMonths As Object
    Set rowByMonths = CreateObject("Scripting.Dictionary")

    Dim nonBizRows As Collection
    Set nonBizRows = New Collection

    Dim n As Long
    Dim months As Long
    Dim r As Long
    Dim rawDate As Date
    Dim adjDate As Date
    r = OUTPUT_FIRST_ROW

    For n = 0 To MAX_QUARTERS
        months = n * 3
        rawDate = IrsAddMonths(effectiveDate, months, useEom)
        adjDate = AdjustModifiedFollowing(rawDate, holidays)

        ws.Cells(r, "A").Value = TenorLabel(months)
        ws.Cells(r, "B").Value = adjDate
        ws.Cells(r, "D").Value = CLng(adjDate - effectiveDate)

        If keyRates.Exists(CStr(months)) Then
            ws.Cells(r, "C").Value = keyRates(CStr(months))
        End If

        rowByMonths(CStr(months)) = r

        If rawDate <> adjDate Then
            nonBizRows.Add Array(TenorLabel(months), rawDate, adjDate, NonBusinessReason(rawDate, holidays))
        End If

        r = r + 1
    Next n

    WriteCurveFormulas ws, keyRates, keyMonths, rowByMonths
    WriteNonBusinessLog ws, nonBizRows, OUTPUT_FIRST_ROW + MAX_QUARTERS + 2
    FormatIRSCurveSheet ws

    Application.CalculateFullRebuild
    MsgBox "완료. Effective Date = " & Format$(effectiveDate, DATE_FORMAT), vbInformation

CleanExit:
    Application.EnableEvents = True
    Application.ScreenUpdating = True
    Exit Sub

Fail:
    Application.EnableEvents = True
    Application.ScreenUpdating = True
    MsgBox "IRS 커브 생성 실패: " & Err.Description, vbCritical
End Sub

Public Sub SetupIRSCurveSheet(ByVal ws As Worksheet)
    ws.Range("D2:V2").Value = Array("기준일", "Call", "CD", "6M", "9M", "1Y", "18M", "2Y", "3Y", _
                                    "4Y", "5Y", "6Y", "7Y", "8Y", "9Y", "10Y", "12Y", "15Y", "20Y")

    ws.Range("D3").NumberFormat = DATE_FORMAT
    ws.Range("E3:V3").NumberFormat = RATE_FORMAT

    With ws.Range("D2:V2")
        .HorizontalAlignment = xlCenter
        .VerticalAlignment = xlCenter
        .Interior.Color = RGB(221, 235, 247)
        .Borders.LineStyle = xlContinuous
    End With

    With ws.Range("D3:V3")
        .HorizontalAlignment = xlCenter
        .VerticalAlignment = xlCenter
        .Borders.LineStyle = xlContinuous
    End With

    CreateOrUpdateRefreshButton ws
End Sub

Private Sub WriteCurveFormulas(ByVal ws As Worksheet, ByVal keyRates As Object, ByVal keyMonths As Variant, ByVal rowByMonths As Object)
    Dim n As Long
    Dim months As Long
    Dim r As Long
    Dim lowerMonths As Long
    Dim upperMonths As Long
    Dim lowerRow As Long
    Dim upperRow As Long

    For n = 0 To MAX_QUARTERS
        months = n * 3
        r = CLng(rowByMonths(CStr(months)))

        If months = 0 Then
            ws.Cells(r, "E").Value = ws.Cells(r, "C").Value
            ws.Cells(r, "F").Value = 0
            ws.Cells(r, "G").Value = 1#
            ws.Cells(r, "H").Value = ws.Cells(r, "E").Value
        Else
            If keyRates.Exists(CStr(months)) Then
                ws.Cells(r, "E").Value = keyRates(CStr(months))
            Else
                FindInterpolationBounds months, keyMonths, lowerMonths, upperMonths
                lowerRow = CLng(rowByMonths(CStr(lowerMonths)))
                upperRow = CLng(rowByMonths(CStr(upperMonths)))
                ws.Cells(r, "E").Formula = "=(E$" & upperRow & "-E$" & lowerRow & ")/(D$" & upperRow & "-D$" & lowerRow & ")*(D" & r & "-D$" & lowerRow & ")+E$" & lowerRow
            End If

            ws.Cells(r, "F").Formula = "=D" & r & "-D" & (r - 1)

            If months = 3 Then
                ws.Cells(r, "G").Formula = "=1/(1+E" & r & "/100*F" & r & "/365)"
            Else
                ws.Cells(r, "G").Formula = "=(36500-E" & r & "*SUMPRODUCT(G$10:G" & (r - 1) & ",F$10:F" & (r - 1) & "))/(36500+F" & r & "*E" & r & ")"
            End If

            ws.Cells(r, "H").Formula = "=-LN(G" & r & ")*365/D" & r & "*100"
        End If
    Next n
End Sub

Private Sub FormatIRSCurveSheet(ByVal ws As Worksheet)
    Dim lastDataRow As Long
    lastDataRow = OUTPUT_FIRST_ROW + MAX_QUARTERS

    With ws.Range("A8:H8")
        .Interior.Color = vbYellow
        .HorizontalAlignment = xlCenter
        .VerticalAlignment = xlCenter
        .Borders.LineStyle = xlContinuous
    End With

    ws.Range("A9:A" & lastDataRow).HorizontalAlignment = xlLeft
    ws.Range("B9:B" & lastDataRow).NumberFormat = DATE_FORMAT
    ws.Range("C9:C" & lastDataRow).NumberFormat = RATE_FORMAT
    ws.Range("D9:D" & lastDataRow).NumberFormat = "0"
    ws.Range("E9:E" & lastDataRow).NumberFormat = RATE_FORMAT
    ws.Range("F9:F" & lastDataRow).NumberFormat = "0"
    ws.Range("G9:H" & lastDataRow).NumberFormat = RATE_FORMAT
    ws.Range("A8:H" & lastDataRow).Borders.LineStyle = xlContinuous

    Dim r As Long
    For r = OUTPUT_FIRST_ROW To lastDataRow
        If Len(ws.Cells(r, "C").Value) > 0 Then
            ws.Cells(r, "A").Interior.Color = vbYellow
        End If
    Next r

    ws.Columns("A:V").AutoFit
End Sub

Private Sub WriteNonBusinessLog(ByVal ws As Worksheet, ByVal nonBizRows As Collection, ByVal startRow As Long)
    If nonBizRows.Count = 0 Then Exit Sub

    ws.Cells(startRow, "A").Value = "비영업일 내역"
    ws.Range(ws.Cells(startRow + 1, "A"), ws.Cells(startRow + 1, "D")).Value = Array("TENOR", "원일", "조정일", "사유")

    Dim i As Long
    Dim item As Variant
    For i = 1 To nonBizRows.Count
        item = nonBizRows(i)
        ws.Cells(startRow + 1 + i, "A").Value = item(0)
        ws.Cells(startRow + 1 + i, "B").Value = item(1)
        ws.Cells(startRow + 1 + i, "C").Value = item(2)
        ws.Cells(startRow + 1 + i, "D").Value = item(3)
    Next i

    With ws.Range(ws.Cells(startRow + 1, "A"), ws.Cells(startRow + 1, "D"))
        .Interior.Color = vbYellow
        .HorizontalAlignment = xlCenter
        .Borders.LineStyle = xlContinuous
    End With

    ws.Range(ws.Cells(startRow + 2, "B"), ws.Cells(startRow + 1 + nonBizRows.Count, "C")).NumberFormat = DATE_FORMAT
    ws.Range(ws.Cells(startRow, "A"), ws.Cells(startRow + 1 + nonBizRows.Count, "D")).Borders.LineStyle = xlContinuous
End Sub

Private Sub CreateOrUpdateRefreshButton(ByVal ws As Worksheet)
    Dim shp As Shape

    On Error Resume Next
    Set shp = ws.Shapes(REFRESH_BUTTON_NAME)
    On Error GoTo 0

    If shp Is Nothing Then
        Set shp = ws.Shapes.AddFormControl(xlButtonControl, ws.Range("A2").Left, ws.Range("A2").Top, _
                                           ws.Range("A2:B3").Width, ws.Range("A2:B3").Height)
        shp.Name = REFRESH_BUTTON_NAME
    End If

    With shp
        .Left = ws.Range("A2").Left
        .Top = ws.Range("A2").Top
        .Width = ws.Range("A2:B3").Width
        .Height = ws.Range("A2:B3").Height
        .OnAction = "'" & ThisWorkbook.Name & "'!RefreshIRSCurve"
        .TextFrame.Characters.Text = "REFRESH"
        .Placement = xlMoveAndSize
    End With
End Sub

Private Function KeyTenorNames() As Variant
    KeyTenorNames = Array("Call", "CD", "6M", "9M", "1Y", "18M", "2Y", "3Y", "4Y", "5Y", _
                          "6Y", "7Y", "8Y", "9Y", "10Y", "12Y", "15Y", "20Y")
End Function

Private Function KeyTenorMonths() As Variant
    KeyTenorMonths = Array(0, 3, 6, 9, 12, 18, 24, 36, 48, 60, 72, 84, 96, 108, 120, 144, 180, 240)
End Function

Private Function TenorLabel(ByVal months As Long) As String
    If months = 0 Then
        TenorLabel = "Call"
    ElseIf months = 3 Then
        TenorLabel = "CD"
    ElseIf months Mod 12 = 0 Then
        TenorLabel = CStr(months \ 12) & "Y"
    Else
        TenorLabel = CStr(months) & "M"
    End If
End Function

Private Sub FindInterpolationBounds(ByVal months As Long, ByVal keyMonths As Variant, ByRef lowerMonths As Long, ByRef upperMonths As Long)
    Dim i As Long

    For i = LBound(keyMonths) To UBound(keyMonths) - 1
        If CLng(keyMonths(i)) < months And months < CLng(keyMonths(i + 1)) Then
            lowerMonths = CLng(keyMonths(i))
            upperMonths = CLng(keyMonths(i + 1))
            Exit Sub
        End If
    Next i

    Err.Raise vbObjectError + 100, , "보간 구간을 찾을 수 없습니다: " & CStr(months) & "M"
End Sub

Private Sub UpdateIrsCalendar(ByVal holidays As Object, ByVal firstYear As Long, ByVal lastYear As Long)
    Dim covered As Object
    Set covered = CreateObject("Scripting.Dictionary")

    Dim y As Long
    Dim ok As Boolean
    holidays.RemoveAll

    For y = firstYear To lastYear
        ok = False

        If AddNagerHolidays(y, holidays) Then ok = True

        If y <= Year(Date) + KRX_LOOKAHEAD_YEARS Then
            If AddKrxHolidays(y, holidays) Then ok = True
        End If

        If ok Then covered(CStr(y)) = True
    Next y

    If Not AllYearsCovered(covered, firstYear, lastYear) Then
        holidays.RemoveAll

        If Not LoadCalendarSheet(holidays, firstYear, lastYear) Then
            Err.Raise vbObjectError + 200, , "휴일 캘린더 갱신 실패. 인터넷 연결 또는 기존 IRS_Calendar 시트를 확인하세요."
        End If

        AddManualHolidays holidays
        MsgBox "휴일 캘린더 갱신 일부 실패: 기존 IRS_Calendar 캐시를 사용했습니다.", vbInformation
        Exit Sub
    End If

    AddManualHolidays holidays
    WriteCalendarSheet holidays
End Sub

Private Function AddKrxHolidays(ByVal y As Long, ByVal holidays As Object) As Boolean
    On Error GoTo Fail

    Dim ref As String
    ref = "https://open.krx.co.kr/contents/MKD/01/0110/01100305/MKD01100305.jsp"

    Dim otpUrl As String
    otpUrl = "https://open.krx.co.kr/contents/COM/GenerateOTP.jspx" & _
             "?bld=MKD%2F01%2F0110%2F01100305%2Fmkd01100305_01&name=form&_=" & CacheStamp()

    Dim otp As String
    otp = FetchText(otpUrl, "GET", "", ref)

    Dim body As String
    body = "search_bas_yy=" & CStr(y) & _
           "&gridTp=KRX" & _
           "&pagePath=%2Fcontents%2FMKD%2F01%2F0110%2F01100305%2FMKD01100305.jsp" & _
           "&code=" & UrlEncode(otp) & _
           "&pageFirstCall=Y"

    Dim json As String
    json = FetchText("https://open.krx.co.kr/contents/OPN/99/OPN99000001.jspx", _
                     "POST", body, "https://open.krx.co.kr/")

    Dim re As Object
    Dim m As Object
    Set re = CreateObject("VBScript.RegExp")
    re.Global = True
    re.Pattern = """calnd_dd"":""(\d{4}-\d{2}-\d{2})""[^}]*""holdy_nm"":""([^""]*)"""

    For Each m In re.Execute(json)
        If IsIrsRelevantKrxHoliday(CStr(m.SubMatches(1))) Then
            AddHoliday holidays, ParseIsoDate(CStr(m.SubMatches(0))), CStr(m.SubMatches(1)), "KRX"
            AddKrxHolidays = True
        End If
    Next m

    Exit Function

Fail:
    AddKrxHolidays = False
End Function

Private Function AddNagerHolidays(ByVal y As Long, ByVal holidays As Object) As Boolean
    On Error GoTo Fail

    Dim json As String
    json = FetchText("https://date.nager.at/api/v3/PublicHolidays/" & CStr(y) & "/KR")

    Dim re As Object
    Dim m As Object
    Set re = CreateObject("VBScript.RegExp")
    re.Global = True
    re.Pattern = """date"":""(\d{4}-\d{2}-\d{2})""[^}]*""localName"":""([^""]*)"""

    For Each m In re.Execute(json)
        AddHoliday holidays, ParseIsoDate(CStr(m.SubMatches(0))), CStr(m.SubMatches(1)), "Nager"
        AddNagerHolidays = True
    Next m

    Exit Function

Fail:
    AddNagerHolidays = False
End Function

Private Function IsIrsRelevantKrxHoliday(ByVal reason As String) As Boolean
    IsIrsRelevantKrxHoliday = True

    If Not INCLUDE_KRX_YEAR_END_CLOSE Then
        If InStr(reason, "연말") > 0 Or InStr(reason, "휴장") > 0 Then
            IsIrsRelevantKrxHoliday = False
        End If
    End If
End Function

Private Sub AddManualHolidays(ByVal holidays As Object)
    On Error Resume Next
    Dim ws As Worksheet
    Set ws = ThisWorkbook.Worksheets("IRS_ManualHolidays")
    On Error GoTo 0

    If ws Is Nothing Then Exit Sub

    Dim r As Long
    Dim lastRow As Long
    lastRow = ws.Cells(ws.Rows.Count, "A").End(xlUp).Row

    For r = 2 To lastRow
        If IsDate(ws.Cells(r, "A").Value) Then
            AddHoliday holidays, CDate(ws.Cells(r, "A").Value), CStr(ws.Cells(r, "B").Value), "Manual"
        End If
    Next r
End Sub

Private Function AdjustModifiedFollowing(ByVal d As Date, ByVal holidays As Object) As Date
    Dim f As Date
    f = FollowingBusinessDay(d, holidays)

    If Month(f) <> Month(d) Or Year(f) <> Year(d) Then
        AdjustModifiedFollowing = PrecedingBusinessDay(d, holidays)
    Else
        AdjustModifiedFollowing = f
    End If
End Function

Private Function AddBusinessDays(ByVal d As Date, ByVal n As Long, ByVal holidays As Object) As Date
    Dim moved As Long

    Do While moved < n
        d = DateAdd("d", 1, d)
        If IsBusinessDay(d, holidays) Then moved = moved + 1
    Loop

    AddBusinessDays = d
End Function

Private Function FollowingBusinessDay(ByVal d As Date, ByVal holidays As Object) As Date
    Do While Not IsBusinessDay(d, holidays)
        d = DateAdd("d", 1, d)
    Loop

    FollowingBusinessDay = d
End Function

Private Function PrecedingBusinessDay(ByVal d As Date, ByVal holidays As Object) As Date
    Do While Not IsBusinessDay(d, holidays)
        d = DateAdd("d", -1, d)
    Loop

    PrecedingBusinessDay = d
End Function

Private Function IsBusinessDay(ByVal d As Date, ByVal holidays As Object) As Boolean
    IsBusinessDay = (Weekday(d, vbMonday) <= 5) And Not holidays.Exists(Format$(d, "yyyymmdd"))
End Function

Private Function IsBusinessMonthEnd(ByVal d As Date, ByVal holidays As Object) As Boolean
    IsBusinessMonthEnd = (d = PrecedingBusinessDay(DateSerial(Year(d), Month(d) + 1, 0), holidays))
End Function

Private Function IrsAddMonths(ByVal d As Date, ByVal months As Long, ByVal useEom As Boolean) As Date
    Dim x As Date
    x = DateAdd("m", months, d)

    If useEom Then
        x = DateSerial(Year(x), Month(x) + 1, 0)
    End If

    IrsAddMonths = x
End Function

Private Function NonBusinessReason(ByVal d As Date, ByVal holidays As Object) As String
    Dim key As String
    Dim reason As String
    key = Format$(d, "yyyymmdd")

    If Weekday(d, vbMonday) > 5 Then reason = "주말"

    If holidays.Exists(key) Then
        If Len(reason) > 0 Then reason = reason & " / "
        reason = reason & CStr(holidays(key))
    End If

    If Len(reason) = 0 Then reason = "영업일"
    NonBusinessReason = reason
End Function

Private Sub AddHoliday(ByVal holidays As Object, ByVal d As Date, ByVal name As String, ByVal source As String)
    Dim key As String
    Dim value As String
    key = Format$(d, "yyyymmdd")
    value = name & " [" & source & "]"

    If holidays.Exists(key) Then
        If InStr(1, CStr(holidays(key)), value, vbTextCompare) = 0 Then
            holidays(key) = CStr(holidays(key)) & " / " & value
        End If
    Else
        holidays(key) = value
    End If
End Sub

Private Function FetchText(ByVal url As String, Optional ByVal method As String = "GET", _
                           Optional ByVal body As String = "", Optional ByVal referer As String = "") As String
    Dim http As Object
    Set http = CreateObject("MSXML2.ServerXMLHTTP.6.0")

    http.setTimeouts 5000, 5000, 15000, 15000
    http.Open method, url, False
    http.setRequestHeader "User-Agent", "Mozilla/5.0"

    If Len(referer) > 0 Then http.setRequestHeader "Referer", referer

    If UCase$(method) = "POST" Then
        http.setRequestHeader "Content-Type", "application/x-www-form-urlencoded"
    End If

    http.Send body

    If http.Status <> 200 Then
        Err.Raise vbObjectError + 300, , "HTTP 오류: " & http.Status & " / " & url
    End If

    FetchText = http.responseText
End Function

Private Function ParseIsoDate(ByVal s As String) As Date
    ParseIsoDate = DateSerial(CInt(Left$(s, 4)), CInt(Mid$(s, 6, 2)), CInt(Right$(s, 2)))
End Function

Private Function CacheStamp() As String
    CacheStamp = Format$(Now, "yyyymmddhhmmss")
End Function

Private Function UrlEncode(ByVal s As String) As String
    Dim i As Long
    Dim ch As String
    Dim c As Long
    Dim out As String

    For i = 1 To Len(s)
        ch = Mid$(s, i, 1)
        c = AscW(ch)

        If (c >= 48 And c <= 57) Or _
           (c >= 65 And c <= 90) Or _
           (c >= 97 And c <= 122) Or _
           ch = "-" Or ch = "_" Or ch = "." Or ch = "~" Then
            out = out & ch
        Else
            out = out & "%" & Right$("0" & Hex$(c And &HFF), 2)
        End If
    Next i

    UrlEncode = out
End Function

Private Function AllYearsCovered(ByVal covered As Object, ByVal firstYear As Long, ByVal lastYear As Long) As Boolean
    Dim y As Long

    For y = firstYear To lastYear
        If Not covered.Exists(CStr(y)) Then Exit Function
    Next y

    AllYearsCovered = True
End Function

Private Sub WriteCalendarSheet(ByVal holidays As Object)
    Dim ws As Worksheet
    Set ws = GetOrCreateSheet("IRS_Calendar")

    ws.Cells.ClearContents
    ws.Range("A1:D1").Value = Array("Date", "Name(Source)", "Key", "UpdatedAt")

    If holidays.Count = 0 Then Exit Sub

    Dim arr() As String
    Dim k As Variant
    Dim i As Long
    ReDim arr(0 To holidays.Count - 1)

    i = 0
    For Each k In holidays.Keys
        arr(i) = CStr(k)
        i = i + 1
    Next k

    SortKeys arr, LBound(arr), UBound(arr)

    Dim r As Long
    r = 2

    For i = LBound(arr) To UBound(arr)
        k = arr(i)
        ws.Cells(r, 1).Value = DateSerial(CInt(Left$(k, 4)), CInt(Mid$(k, 5, 2)), CInt(Right$(k, 2)))
        ws.Cells(r, 2).Value = holidays(k)
        ws.Cells(r, 3).Value = CStr(k)
        ws.Cells(r, 4).Value = Now
        r = r + 1
    Next i

    ws.Range("A:A").NumberFormat = DATE_FORMAT
    ws.Columns("A:D").AutoFit
End Sub

Private Sub SortKeys(ByRef arr() As String, ByVal first As Long, ByVal last As Long)
    Dim low As Long
    Dim high As Long
    Dim mid As String
    Dim temp As String

    low = first
    high = last
    mid = arr((first + last) \ 2)

    Do While low <= high
        Do While arr(low) < mid
            low = low + 1
        Loop

        Do While arr(high) > mid
            high = high - 1
        Loop

        If low <= high Then
            temp = arr(low)
            arr(low) = arr(high)
            arr(high) = temp
            low = low + 1
            high = high - 1
        End If
    Loop

    If first < high Then SortKeys arr, first, high
    If low < last Then SortKeys arr, low, last
End Sub

Private Function LoadCalendarSheet(ByVal holidays As Object, ByVal firstYear As Long, ByVal lastYear As Long) As Boolean
    On Error GoTo Fail

    Dim ws As Worksheet
    Set ws = ThisWorkbook.Worksheets("IRS_Calendar")

    Dim covered As Object
    Set covered = CreateObject("Scripting.Dictionary")

    Dim r As Long
    Dim lastRow As Long
    Dim d As Date
    lastRow = ws.Cells(ws.Rows.Count, "A").End(xlUp).Row

    For r = 2 To lastRow
        If IsDate(ws.Cells(r, "A").Value) Then
            d = CDate(ws.Cells(r, "A").Value)

            If Year(d) >= firstYear And Year(d) <= lastYear Then
                holidays(Format$(d, "yyyymmdd")) = CStr(ws.Cells(r, "B").Value) & " [Cached]"
                covered(CStr(Year(d))) = True
            End If
        End If
    Next r

    LoadCalendarSheet = AllYearsCovered(covered, firstYear, lastYear)
    Exit Function

Fail:
    LoadCalendarSheet = False
End Function

Private Function GetOrCreateSheet(ByVal sheetName As String) As Worksheet
    On Error Resume Next
    Set GetOrCreateSheet = ThisWorkbook.Worksheets(sheetName)
    On Error GoTo 0

    If GetOrCreateSheet Is Nothing Then
        Set GetOrCreateSheet = ThisWorkbook.Worksheets.Add(After:=ThisWorkbook.Worksheets(ThisWorkbook.Worksheets.Count))
        GetOrCreateSheet.Name = sheetName
    End If
End Function
