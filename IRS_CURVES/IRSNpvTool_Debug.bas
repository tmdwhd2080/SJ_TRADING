Option Explicit

Private Const USE_EOM_CONVENTION As Boolean = True
Private Const INCLUDE_KRX_YEAR_END_CLOSE As Boolean = False
Private Const KRX_LOOKAHEAD_YEARS As Long = 5

Private Const INPUT_HEADER_ROW As Long = 2
Private Const INPUT_VALUE_ROW As Long = 3

Private Const COL_EFFECTIVE_DATE As Long = 1     ' A
Private Const COL_MATURITY_DATE As Long = 2      ' B
Private Const COL_VALUATION_DATE As Long = 3     ' C
Private Const COL_NOTIONAL As Long = 4           ' D
Private Const COL_DAY_BASIS As Long = 5          ' E
Private Const COL_FIXED_RATE As Long = 6         ' F
Private Const RATE_INPUT_FIRST_COL As Long = 7   ' G

Private Const SCHEDULE_FIRST_COL As Long = 2     ' B
Private Const SCHED_ROW_START As Long = 5
Private Const SCHED_ROW_END As Long = 6
Private Const SCHED_ROW_DAYS As Long = 7
Private Const SCHED_ROW_ACCRUAL As Long = 8
Private Const SCHED_ROW_FORWARD As Long = 9
Private Const SCHED_ROW_COUPON_RATE As Long = 10
Private Const SCHED_ROW_PAY_DF As Long = 11
Private Const SCHED_ROW_FIXED_COUPON As Long = 12
Private Const SCHED_ROW_FLOAT_COUPON As Long = 13
Private Const SCHED_ROW_FIXED_PV As Long = 14
Private Const SCHED_ROW_FLOAT_PV As Long = 15
Private Const SCHED_ROW_NET_PV As Long = 16

Private Const SUMMARY_ROW As Long = 23
Private Const CASHFLOW_CUTOFF_LABEL_CELL As String = "$AA$2"
Private Const CASHFLOW_CUTOFF_CELL As String = "$AA$3"
Private Const CASHFLOW_CUTOFF_LAG_BD As Long = 1
Private Const OUTPUT_HEADER_ROW As Long = 27
Private Const OUTPUT_FIRST_ROW As Long = 28
Private Const MAX_QUARTERS As Long = 80

Private Const REFRESH_BUTTON_NAME As String = "btnRefreshIRSNpv"
Private Const CALENDAR_UPDATE_BUTTON_NAME As String = "btnUpdateIrsCalendar"
Private Const CALENDAR_UPDATE_FIRST_YEAR As Long = 2020
Private Const CALENDAR_UPDATE_LAST_YEAR As Long = 2040
Private Const RATE_FORMAT As String = "0.0000000000"
Private Const AMOUNT_FORMAT As String = "#,##0.0000000000"
Private Const DATE_FORMAT As String = "yyyy-mm-dd"
Private Const CD_FIXINGS_SHEET As String = "CD_Fixings"
Private Const DV01_BUMP_RATE As Double = 0.01

Private gIrsTargetWorkbook As Workbook
Private gIrsCurrentStep As String

Public Sub RefreshIRSNpvTool()
    On Error GoTo Fail

    Dim ws As Worksheet

    SetIrsStep "Set active sheet"
    Set ws = ActiveSheet
    Set gIrsTargetWorkbook = ws.Parent

    SetIrsStep "Check workbook and sheet protection"
    EnsureWritableIrsTarget ws

    SetIrsStep "Disable Excel UI updates"
    Application.ScreenUpdating = False
    Application.EnableEvents = False

    SetIrsStep "Setup IRS NPV sheet"
    SetupIRSNpvSheet ws

    SetIrsStep "Ensure CD_Fixings sheet"
    EnsureCdFixingsSheet

    SetIrsStep "Validate inputs"
    If Not ValidateInputs(ws) Then GoTo CleanExit

    Dim effectiveDate As Date
    Dim maturityDate As Date
    Dim valuationDate As Date

    SetIrsStep "Read input dates"
    effectiveDate = CDate(ws.Cells(INPUT_VALUE_ROW, COL_EFFECTIVE_DATE).Value)
    maturityDate = CDate(ws.Cells(INPUT_VALUE_ROW, COL_MATURITY_DATE).Value)
    valuationDate = CDate(ws.Cells(INPUT_VALUE_ROW, COL_VALUATION_DATE).Value)

    Dim firstYear As Long
    Dim lastYear As Long
    firstYear = MinLong(Year(effectiveDate), Year(valuationDate))
    lastYear = MaxLong(Year(DateAdd("yyyy", 1, valuationDate)), Year(DateAdd("yyyy", 1, maturityDate)))

    Dim holidays As Object
    Set holidays = CreateObject("Scripting.Dictionary")

    SetIrsStep "Load IRS_Calendar cache"
    UpdateIrsCalendar holidays, firstYear, lastYear

    Dim cashflowCutoffDate As Date

    SetIrsStep "Calculate cashflow cutoff date"
    cashflowCutoffDate = AddBusinessDays(valuationDate, CASHFLOW_CUTOFF_LAG_BD, holidays)

    Dim keyMonths As Variant
    keyMonths = KeyTenorMonths()

    Dim keyRates As Object

    SetIrsStep "Read market rates"
    Set keyRates = ReadKeyRates(ws, keyMonths)

    SetIrsStep "Clear old output"
    ws.Range("A5:CC500").Clear
    ws.Columns("ZZ").ClearContents
    ws.Range(CASHFLOW_CUTOFF_LABEL_CELL).Value = KoreanValuationDatePlusTwoBusinessDaysLabel()
    ws.Range(CASHFLOW_CUTOFF_CELL).Value = cashflowCutoffDate

    Dim nonBizRows As Collection
    Set nonBizRows = New Collection

    Dim couponCount As Long

    SetIrsStep "Write cashflow schedule"
    couponCount = WriteCashflowSchedule(ws, effectiveDate, maturityDate, valuationDate, cashflowCutoffDate, holidays, nonBizRows)

    SetIrsStep "Prefetch missing CD fixings"
    PrefetchMissingCdFixings ws, couponCount, cashflowCutoffDate

    Dim curveQuarterCount As Long

    SetIrsStep "Calculate curve horizon"
    curveQuarterCount = CurveQuarterCountThroughDate(valuationDate, MaxScheduledPaymentDate(ws, couponCount, maturityDate), holidays)
    curveQuarterCount = ExtendCurveQuarterCountToInterpolationUpperKey(curveQuarterCount, keyMonths)

    SetIrsStep "Write quarterly curve"
    WriteQuarterlyCurve ws, valuationDate, keyRates, keyMonths, holidays, nonBizRows, curveQuarterCount

    SetIrsStep "Write NPV summary"
    WriteNpvSummary ws, couponCount

    SetIrsStep "Write DF lookup box"
    WriteDfLookupBox ws, curveQuarterCount

    SetIrsStep "Write non-business day log"
    WriteNonBusinessLog ws, nonBizRows, OUTPUT_FIRST_ROW + curveQuarterCount + 3

    SetIrsStep "Format output sheet"
    FormatIRSNpvSheet ws, couponCount, curveQuarterCount

    SetIrsStep "Calculate worksheet"
    ws.Calculate

    MsgBox "Done. Valuation Date = " & Format$(valuationDate, DATE_FORMAT), vbInformation

CleanExit:
    Application.EnableEvents = True
    Application.ScreenUpdating = True
    Set gIrsTargetWorkbook = Nothing
    Exit Sub

Fail:
    Dim errNo As Long
    Dim errDesc As String
    Dim errSource As String
    Dim errLine As Long

    errNo = Err.Number
    errDesc = Err.Description
    errSource = Err.Source
    errLine = Erl

    Application.EnableEvents = True
    Application.ScreenUpdating = True

    MsgBox BuildIrsErrorMessage("IRS NPV refresh failed", errNo, errDesc, errSource, errLine, ws), vbCritical
    Set gIrsTargetWorkbook = Nothing
End Sub
Public Sub SetupIRSNpvSheet(ByVal ws As Worksheet)
    ws.Cells(INPUT_HEADER_ROW, COL_EFFECTIVE_DATE).value = "Effective Date"
    ws.Cells(INPUT_HEADER_ROW, COL_MATURITY_DATE).value = "Maturity Date"
    ws.Cells(INPUT_HEADER_ROW, COL_VALUATION_DATE).value = KoreanValuationDatePlusOneBusinessDayLabel()
    ws.Cells(INPUT_HEADER_ROW, COL_NOTIONAL).value = "Notional Amount"
    ws.Cells(INPUT_HEADER_ROW, COL_DAY_BASIS).value = "Day Basis"
    ws.Cells(INPUT_HEADER_ROW, COL_FIXED_RATE).value = "Fixed Rate"
    ws.Range(CASHFLOW_CUTOFF_LABEL_CELL).value = KoreanValuationDatePlusTwoBusinessDaysLabel()

    ws.Range(ws.Cells(INPUT_HEADER_ROW, RATE_INPUT_FIRST_COL), _
             ws.Cells(INPUT_HEADER_ROW, RATE_INPUT_FIRST_COL + UBound(KeyTenorNames()))).value = KeyTenorNames()

    ws.Range("A3:C3").NumberFormat = DATE_FORMAT
    ws.Range(CASHFLOW_CUTOFF_CELL).NumberFormat = DATE_FORMAT
    ws.Cells(INPUT_VALUE_ROW, COL_NOTIONAL).NumberFormat = AMOUNT_FORMAT
    ws.Cells(INPUT_VALUE_ROW, COL_DAY_BASIS).NumberFormat = "0"
    ws.Cells(INPUT_VALUE_ROW, COL_FIXED_RATE).NumberFormat = RATE_FORMAT
    ws.Range(ws.Cells(INPUT_VALUE_ROW, RATE_INPUT_FIRST_COL), _
             ws.Cells(INPUT_VALUE_ROW, RATE_INPUT_FIRST_COL + UBound(KeyTenorNames()))).NumberFormat = RATE_FORMAT

    With ws.Range(ws.Cells(INPUT_HEADER_ROW, 1), _
                  ws.Cells(INPUT_HEADER_ROW, RATE_INPUT_FIRST_COL + UBound(KeyTenorNames())))
        .HorizontalAlignment = xlCenter
        .VerticalAlignment = xlCenter
        .Interior.Color = RGB(221, 235, 247)
        .Borders.LineStyle = xlContinuous
    End With

    With ws.Range(CASHFLOW_CUTOFF_LABEL_CELL)
        .HorizontalAlignment = xlCenter
        .VerticalAlignment = xlCenter
        .Interior.Color = RGB(221, 235, 247)
        .Borders.LineStyle = xlContinuous
    End With

    With ws.Range(ws.Cells(INPUT_VALUE_ROW, 1), _
                  ws.Cells(INPUT_VALUE_ROW, RATE_INPUT_FIRST_COL + UBound(KeyTenorNames())))
        .HorizontalAlignment = xlCenter
        .VerticalAlignment = xlCenter
        .Borders.LineStyle = xlContinuous
    End With

    With ws.Range(CASHFLOW_CUTOFF_CELL)
        .HorizontalAlignment = xlCenter
        .VerticalAlignment = xlCenter
        .Borders.LineStyle = xlContinuous
    End With

    CreateOrUpdateRefreshButton ws
End Sub

Private Function ValidateInputs(ByVal ws As Worksheet) As Boolean
    If Not IsDate(ws.Cells(INPUT_VALUE_ROW, COL_EFFECTIVE_DATE).value) Then
        MsgBox "Enter Effective Date in A3.", vbExclamation
        Exit Function
    End If

    If Not IsDate(ws.Cells(INPUT_VALUE_ROW, COL_MATURITY_DATE).value) Then
        MsgBox "Enter Maturity Date in B3.", vbExclamation
        Exit Function
    End If

    If Not IsDate(ws.Cells(INPUT_VALUE_ROW, COL_VALUATION_DATE).value) Then
        MsgBox "Enter valuation date in C3.", vbExclamation
        Exit Function
    End If

    If CDate(ws.Cells(INPUT_VALUE_ROW, COL_EFFECTIVE_DATE).value) >= _
       CDate(ws.Cells(INPUT_VALUE_ROW, COL_MATURITY_DATE).value) Then
        MsgBox "Maturity Date must be later than Effective Date.", vbExclamation
        Exit Function
    End If

    If Not IsNumeric(ws.Cells(INPUT_VALUE_ROW, COL_NOTIONAL).value) Then
        MsgBox "Enter Notional Amount in D3.", vbExclamation
        Exit Function
    End If

    If Not IsNumeric(ws.Cells(INPUT_VALUE_ROW, COL_DAY_BASIS).value) Then
        MsgBox "Enter Day Basis in E3, such as 365 or 360.", vbExclamation
        Exit Function
    End If

    If CDbl(ws.Cells(INPUT_VALUE_ROW, COL_DAY_BASIS).value) <= 0 Then
        MsgBox "Day Basis must be positive.", vbExclamation
        Exit Function
    End If

    If Not IsNumeric(ws.Cells(INPUT_VALUE_ROW, COL_FIXED_RATE).value) Then
        MsgBox "Enter Fixed Rate in F3 as a percent number, such as 3.305.", vbExclamation
        Exit Function
    End If

    Dim keyNames As Variant
    keyNames = KeyTenorNames()

    Dim i As Long
    For i = LBound(keyNames) To UBound(keyNames)
        If Not IsNumeric(ws.Cells(INPUT_VALUE_ROW, RATE_INPUT_FIRST_COL + i).value) Then
            MsgBox "Enter numeric rate for " & CStr(keyNames(i)) & ".", vbExclamation
            Exit Function
        End If
    Next i

    ValidateInputs = True
End Function

Private Function ReadKeyRates(ByVal ws As Worksheet, ByVal keyMonths As Variant) As Object
    Dim rates As Object
    Set rates = CreateObject("Scripting.Dictionary")

    Dim i As Long
    For i = LBound(keyMonths) To UBound(keyMonths)
        rates(CStr(keyMonths(i))) = CDbl(ws.Cells(INPUT_VALUE_ROW, RATE_INPUT_FIRST_COL + i).value)
    Next i

    Set ReadKeyRates = rates
End Function

Private Function WriteCashflowSchedule(ByVal ws As Worksheet, ByVal effectiveDate As Date, _
                                       ByVal maturityDate As Date, ByVal valuationDate As Date, _
                                       ByVal cashflowCutoffDate As Date, _
                                       ByVal holidays As Object, ByVal nonBizRows As Collection) As Long
    ws.Cells(SCHED_ROW_START, "A").value = "Accrual Start / Fixing Date"
    ws.Cells(SCHED_ROW_END, "A").value = "Accrual End / Coupon Date / Payment Date"
    ws.Cells(SCHED_ROW_DAYS, "A").value = "Accrual Days"
    ws.Cells(SCHED_ROW_ACCRUAL, "A").value = "Accrual Factor"
    ws.Cells(SCHED_ROW_FORWARD, "A").value = "Forward Rate"
    ws.Cells(SCHED_ROW_COUPON_RATE, "A").value = "Coupon Rate Used"
    ws.Cells(SCHED_ROW_PAY_DF, "A").value = "Pay DF"
    ws.Cells(SCHED_ROW_FIXED_COUPON, "A").value = "Fixed Coupon"
    ws.Cells(SCHED_ROW_FLOAT_COUPON, "A").value = "Floating Coupon"
    ws.Cells(SCHED_ROW_FIXED_PV, "A").value = "Fixed PV"
    ws.Cells(SCHED_ROW_FLOAT_PV, "A").value = "Floating PV"
    ws.Cells(SCHED_ROW_NET_PV, "A").value = "Net PV Float-Fixed"

    Dim useEom As Boolean
    useEom = USE_EOM_CONVENTION And IsBusinessMonthEnd(effectiveDate, holidays)

    Dim periodNo As Long
    Dim outCol As Long
    Dim rawStart As Date
    Dim rawEnd As Date
    Dim adjStart As Date
    Dim adjEnd As Date
    Dim writtenCoupons As Long

    periodNo = 1
    outCol = SCHEDULE_FIRST_COL
    writtenCoupons = 0

    Do While periodNo <= MAX_QUARTERS
        rawStart = IrsAddMonths(effectiveDate, (periodNo - 1) * 3, useEom)
        If rawStart >= maturityDate Then Exit Do

        rawEnd = IrsAddMonths(effectiveDate, periodNo * 3, useEom)
        If rawEnd > maturityDate Then rawEnd = maturityDate

        adjStart = AdjustModifiedFollowing(rawStart, holidays)
        adjEnd = AdjustModifiedFollowing(rawEnd, holidays)

        If rawStart <> adjStart Then nonBizRows.Add Array("Schedule Start", rawStart, adjStart, NonBusinessReason(rawStart, holidays))
        If rawEnd <> adjEnd Then nonBizRows.Add Array("Schedule End/Pay", rawEnd, adjEnd, NonBusinessReason(rawEnd, holidays))

        If adjEnd >= cashflowCutoffDate Then
            ws.Cells(SCHED_ROW_START, outCol).value = adjStart
            ws.Cells(SCHED_ROW_END, outCol).value = adjEnd

            WriteCashflowFormulas ws, outCol

            writtenCoupons = writtenCoupons + 1
            outCol = outCol + 1
        End If

        periodNo = periodNo + 1
    Loop

    If rawEnd < maturityDate Then
        Err.Raise vbObjectError + 101, , "Schedule is longer than MAX_QUARTERS."
    End If

    WriteCashflowSchedule = writtenCoupons
End Function

Private Sub WriteCashflowFormulas(ByVal ws As Worksheet, ByVal c As Long)
    Dim startCell As String
    Dim endCell As String
    Dim payCell As String
    Dim fixingDateCell As String
    Dim daysCell As String
    Dim accrualCell As String
    Dim forwardCell As String
    Dim couponRateCell As String
    Dim payDfCell As String
    Dim fixedCouponCell As String
    Dim floatCouponCell As String
    Dim fixedPvCell As String
    Dim floatPvCell As String

    startCell = ws.Cells(SCHED_ROW_START, c).Address(False, False)
    endCell = ws.Cells(SCHED_ROW_END, c).Address(False, False)
    payCell = endCell
    fixingDateCell = startCell
    daysCell = ws.Cells(SCHED_ROW_DAYS, c).Address(False, False)
    accrualCell = ws.Cells(SCHED_ROW_ACCRUAL, c).Address(False, False)
    forwardCell = ws.Cells(SCHED_ROW_FORWARD, c).Address(False, False)
    couponRateCell = ws.Cells(SCHED_ROW_COUPON_RATE, c).Address(False, False)
    payDfCell = ws.Cells(SCHED_ROW_PAY_DF, c).Address(False, False)
    fixedCouponCell = ws.Cells(SCHED_ROW_FIXED_COUPON, c).Address(False, False)
    floatCouponCell = ws.Cells(SCHED_ROW_FLOAT_COUPON, c).Address(False, False)
    fixedPvCell = ws.Cells(SCHED_ROW_FIXED_PV, c).Address(False, False)
    floatPvCell = ws.Cells(SCHED_ROW_FLOAT_PV, c).Address(False, False)

    ws.Cells(SCHED_ROW_DAYS, c).Formula = _
        "=IF(" & payCell & "<" & CASHFLOW_CUTOFF_CELL & ",0," & endCell & "-" & startCell & ")"
    ws.Cells(SCHED_ROW_ACCRUAL, c).Formula = "=" & daysCell & "/$E$3"

    ws.Cells(SCHED_ROW_FORWARD, c).Formula = _
        "=IF(" & payCell & "<" & CASHFLOW_CUTOFF_CELL & ",0,IF(" & fixingDateCell & "<=" & CASHFLOW_CUTOFF_CELL & ","""",IFERROR((IRS_DAILY_DF(" & startCell & ")/IRS_DAILY_DF(" & payCell & ")-1)/((" & payCell & "-" & startCell & ")/$E$3)*100,"""")))"

    ws.Cells(SCHED_ROW_COUPON_RATE, c).Formula = _
        "=IF(" & payCell & "<" & CASHFLOW_CUTOFF_CELL & ",0,IF(" & fixingDateCell & "<=" & CASHFLOW_CUTOFF_CELL & ",IFERROR(VLOOKUP(" & fixingDateCell & "," & CD_FIXINGS_SHEET & "!$A:$B,2,FALSE),NA())," & forwardCell & "))"

    ws.Cells(SCHED_ROW_PAY_DF, c).Formula = _
        "=IF(" & payCell & "<" & CASHFLOW_CUTOFF_CELL & ",0,IRS_DAILY_DF(" & payCell & "))"

    ws.Cells(SCHED_ROW_FIXED_COUPON, c).Formula = _
        "=IF(" & payCell & "<" & CASHFLOW_CUTOFF_CELL & ",0,$D$3*$F$3/100*" & accrualCell & ")"

    ws.Cells(SCHED_ROW_FLOAT_COUPON, c).Formula = _
        "=IF(" & payCell & "<" & CASHFLOW_CUTOFF_CELL & ",0,$D$3*" & couponRateCell & "/100*" & accrualCell & ")"

    ws.Cells(SCHED_ROW_FIXED_PV, c).Formula = "=" & fixedCouponCell & "*" & payDfCell
    ws.Cells(SCHED_ROW_FLOAT_PV, c).Formula = "=" & floatCouponCell & "*" & payDfCell
    ws.Cells(SCHED_ROW_NET_PV, c).Formula = "=" & floatPvCell & "-" & fixedPvCell
End Sub

Private Sub WriteQuarterlyCurve(ByVal ws As Worksheet, ByVal valuationDate As Date, ByVal keyRates As Object, _
                                ByVal keyMonths As Variant, ByVal holidays As Object, _
                                ByVal nonBizRows As Collection, ByVal curveQuarterCount As Long)
    ws.Range(ws.Cells(OUTPUT_HEADER_ROW, "A"), ws.Cells(OUTPUT_HEADER_ROW, "I")).value = _
        Array("TENOR", "Date", "Par Rate", "Days From Base", "Interpolated Par Rate", "Accrual Days", "DF", "ZCR", "DV01")

    Dim rowByMonths As Object
    Set rowByMonths = CreateObject("Scripting.Dictionary")

    Dim useEom As Boolean
    useEom = USE_EOM_CONVENTION And IsBusinessMonthEnd(valuationDate, holidays)

    Dim n As Long
    Dim months As Long
    Dim r As Long
    Dim rawDate As Date
    Dim adjDate As Date

    r = OUTPUT_FIRST_ROW

    For n = 0 To curveQuarterCount
        months = n * 3

        If months = 0 Then
            rawDate = valuationDate
            adjDate = valuationDate
        Else
            rawDate = IrsAddMonths(valuationDate, months, useEom)
            adjDate = AdjustModifiedFollowing(rawDate, holidays)
        End If

        ws.Cells(r, "A").value = TenorLabel(months)
        ws.Cells(r, "B").value = adjDate
        ws.Cells(r, "D").value = CLng(adjDate - valuationDate)

        If keyRates.Exists(CStr(months)) Then
            ws.Cells(r, "C").value = CDbl(keyRates(CStr(months)))
        End If

        rowByMonths(CStr(months)) = r

        If rawDate <> adjDate Then
            nonBizRows.Add Array(TenorLabel(months), rawDate, adjDate, NonBusinessReason(rawDate, holidays))
        End If

        r = r + 1
    Next n

    WriteCurveFormulas ws, keyRates, keyMonths, rowByMonths, curveQuarterCount
    WriteDv01Formulas ws, curveQuarterCount
End Sub

Private Sub WriteCurveFormulas(ByVal ws As Worksheet, ByVal keyRates As Object, _
                               ByVal keyMonths As Variant, ByVal rowByMonths As Object, _
                               ByVal curveQuarterCount As Long)
    Dim n As Long
    Dim months As Long
    Dim r As Long
    Dim lowerMonths As Long
    Dim upperMonths As Long
    Dim lowerRow As Long
    Dim upperRow As Long
    Dim firstCouponRow As Long

    firstCouponRow = OUTPUT_FIRST_ROW + 1

    For n = 0 To curveQuarterCount
        months = n * 3
        r = CLng(rowByMonths(CStr(months)))

        If months = 0 Then
            ws.Cells(r, "E").Formula = "=C" & r
            ws.Cells(r, "F").value = 0
            ws.Cells(r, "G").value = 1#
            ws.Cells(r, "H").Formula = "=E" & r
        Else
            If keyRates.Exists(CStr(months)) Then
                ws.Cells(r, "E").Formula = "=C" & r
            Else
                FindInterpolationBounds months, keyMonths, lowerMonths, upperMonths
                If Not rowByMonths.Exists(CStr(lowerMonths)) Or _
                   Not rowByMonths.Exists(CStr(upperMonths)) Then
                    Err.Raise vbObjectError + 103, , "Curve grid does not include interpolation bound for " & _
                                                    CStr(months) & "M. Need " & CStr(lowerMonths) & _
                                                    "M and " & CStr(upperMonths) & "M rows."
                End If

                lowerRow = CLng(rowByMonths(CStr(lowerMonths)))
                upperRow = CLng(rowByMonths(CStr(upperMonths)))
                ws.Cells(r, "E").Formula = "=(E$" & upperRow & "-E$" & lowerRow & ")/(D$" & upperRow & "-D$" & lowerRow & ")*(D" & r & "-D$" & lowerRow & ")+E$" & lowerRow
            End If

            ws.Cells(r, "F").Formula = "=D" & r & "-D" & (r - 1)

            If months = 3 Then
                ws.Cells(r, "G").Formula = "=1/(1+E" & r & "/100*F" & r & "/$E$3)"
            Else
                ws.Cells(r, "G").Formula = "=($E$3*100-E" & r & "*SUMPRODUCT(G$" & firstCouponRow & ":G" & (r - 1) & ",F$" & firstCouponRow & ":F" & (r - 1) & "))/($E$3*100+F" & r & "*E" & r & ")"
            End If

            ws.Cells(r, "H").Formula = "=-LN(G" & r & ")*$E$3/D" & r & "*100"
        End If
    Next n
End Sub

Private Sub WriteDv01Formulas(ByVal ws As Worksheet, ByVal curveQuarterCount As Long)
    Dim r As Long
    Dim lastCurveRow As Long

    lastCurveRow = OUTPUT_FIRST_ROW + curveQuarterCount

    For r = OUTPUT_FIRST_ROW To lastCurveRow
        ws.Cells(r, "I").Formula = _
            "=IF(C" & r & "="""","""",IRS_TENOR_DV01(A" & r & "))"
    Next r
End Sub

Private Sub WriteNpvSummary(ByVal ws As Worksheet, ByVal couponCount As Long)
    Dim firstCol As Long
    Dim lastCol As Long
    firstCol = SCHEDULE_FIRST_COL

    ws.Cells(SUMMARY_ROW, "A").value = "PV Fixed"
    ws.Cells(SUMMARY_ROW, "C").value = "PV Floating"
    ws.Cells(SUMMARY_ROW, "E").value = "NPV Float-Fixed"
    ws.Cells(SUMMARY_ROW + 1, "A").value = "View"
    ws.Cells(SUMMARY_ROW + 1, "B").value = "Floating receiver / fixed payer"

    If couponCount <= 0 Then
        ws.Cells(SUMMARY_ROW, "B").value = 0
        ws.Cells(SUMMARY_ROW, "D").value = 0
        ws.Cells(SUMMARY_ROW, "F").value = 0
        Exit Sub
    End If

    lastCol = SCHEDULE_FIRST_COL + couponCount - 1
    ws.Cells(SUMMARY_ROW, "B").Formula = "=SUM(" & ws.Range(ws.Cells(SCHED_ROW_FIXED_PV, firstCol), ws.Cells(SCHED_ROW_FIXED_PV, lastCol)).Address(False, False) & ")"

    ws.Cells(SUMMARY_ROW, "D").Formula = "=SUM(" & ws.Range(ws.Cells(SCHED_ROW_FLOAT_PV, firstCol), ws.Cells(SCHED_ROW_FLOAT_PV, lastCol)).Address(False, False) & ")"

    ws.Cells(SUMMARY_ROW, "F").Formula = "=D" & SUMMARY_ROW & "-B" & SUMMARY_ROW
End Sub

Private Function MaxScheduledPaymentDate(ByVal ws As Worksheet, ByVal couponCount As Long, ByVal fallbackDate As Date) As Date
    If couponCount <= 0 Then
        MaxScheduledPaymentDate = fallbackDate
        Exit Function
    End If

    Dim c As Long
    Dim lastCol As Long
    Dim d As Date
    Dim maxDate As Date

    lastCol = SCHEDULE_FIRST_COL + couponCount - 1
    maxDate = fallbackDate

    For c = SCHEDULE_FIRST_COL To lastCol
        If IsDate(ws.Cells(SCHED_ROW_END, c).value) Then
            d = CDate(ws.Cells(SCHED_ROW_END, c).value)
            If d > maxDate Then maxDate = d
        End If
    Next c

    MaxScheduledPaymentDate = maxDate
End Function

Private Function CurveQuarterCountThroughDate(ByVal valuationDate As Date, ByVal horizonDate As Date, _
                                              ByVal holidays As Object) As Long
    Dim useEom As Boolean
    useEom = USE_EOM_CONVENTION And IsBusinessMonthEnd(valuationDate, holidays)

    Dim n As Long
    Dim rawDate As Date
    Dim adjDate As Date

    For n = 0 To MAX_QUARTERS
        If n = 0 Then
            adjDate = valuationDate
        Else
            rawDate = IrsAddMonths(valuationDate, n * 3, useEom)
            adjDate = AdjustModifiedFollowing(rawDate, holidays)
        End If

        If adjDate >= horizonDate Then
            CurveQuarterCountThroughDate = n
            Exit Function
        End If
    Next n

    Err.Raise vbObjectError + 102, , "Curve horizon is longer than MAX_QUARTERS."
End Function


Private Function ExtendCurveQuarterCountToInterpolationUpperKey(ByVal curveQuarterCount As Long, _
                                                               ByVal keyMonths As Variant) As Long
    Dim months As Long
    Dim i As Long

    months = curveQuarterCount * 3

    For i = LBound(keyMonths) To UBound(keyMonths)
        If CLng(keyMonths(i)) >= months Then
            ExtendCurveQuarterCountToInterpolationUpperKey = CLng(keyMonths(i)) \ 3
            Exit Function
        End If
    Next i

    ExtendCurveQuarterCountToInterpolationUpperKey = curveQuarterCount
End Function
Private Sub WriteDfLookupBox(ByVal ws As Worksheet, ByVal curveQuarterCount As Long)
    Dim lookupRow As Long
    Dim lastCurveRow As Long
    Dim lookupDateCell As String
    Dim dailyZcrCell As String
    Dim curveDateRange As String
    Dim curveZcrRange As String

    lookupRow = SUMMARY_ROW + 1
    lastCurveRow = OUTPUT_FIRST_ROW + curveQuarterCount

    lookupDateCell = ws.Cells(lookupRow, "J").Address(False, False)
    dailyZcrCell = ws.Cells(lookupRow, "L").Address(False, False)
    curveDateRange = ws.Range(ws.Cells(OUTPUT_FIRST_ROW, "B"), ws.Cells(lastCurveRow, "B")).Address(True, True)
    curveZcrRange = ws.Range(ws.Cells(OUTPUT_FIRST_ROW, "H"), ws.Cells(lastCurveRow, "H")).Address(True, True)

    ws.Cells(SUMMARY_ROW, "J").value = "Daily ZCR/DF"
    ws.Cells(SUMMARY_ROW, "K").value = "Daily DF"
    ws.Cells(SUMMARY_ROW, "L").value = "Daily ZCR"
    ws.Cells(lookupRow, "J").ClearContents

    ws.Cells(lookupRow, "K").Formula = _
        "=IF(" & lookupDateCell & "="""","""",IFERROR(EXP(-" & dailyZcrCell & "/100*(" & lookupDateCell & "-$C$3)/$E$3),NA()))"

    ws.Cells(lookupRow, "L").Formula = _
        "=IF(" & lookupDateCell & "="""","""",LET(target," & lookupDateCell & ",dateRange," & curveDateRange & ",zcrRange," & curveZcrRange & ",baseDate,$C$3,IF(NOT(ISNUMBER(target)),NA(),IF(target<baseDate,NA(),IFERROR(INDEX(zcrRange,MATCH(target,dateRange,0)),IF(target>INDEX(dateRange,ROWS(dateRange)),NA(),LET(periodIndex,MATCH(target,dateRange,1),dateLow,INDEX(dateRange,periodIndex),dateHigh,INDEX(dateRange,periodIndex+1),zcrLow,INDEX(zcrRange,periodIndex),zcrHigh,INDEX(zcrRange,periodIndex+1),zcrLow+(zcrHigh-zcrLow)*(target-dateLow)/(dateHigh-dateLow))))))))"
End Sub

Public Function IRS_TENOR_DV01(ByVal tenor As Variant, Optional ByVal sheetName As String = "") As Variant
    On Error GoTo Fail
    Application.Volatile True

    Dim shockedMonths As Long
    If Not TryParseTenorMonths(tenor, shockedMonths) Then
        IRS_TENOR_DV01 = CVErr(xlErrValue)
        Exit Function
    End If

    Dim ws As Worksheet
    If Len(sheetName) > 0 Then
        Set ws = IrsTargetWorkbook().Worksheets(sheetName)
    ElseIf TypeName(Application.Caller) = "Range" Then
        Set ws = Application.Caller.Worksheet
    Else
        Set ws = ActiveSheet
    End If

    Dim baseNpv As Double
    Dim upNpv As Double
    Dim downNpv As Double

    baseNpv = IrsNpvForRateShock(ws, shockedMonths, 0#)
    upNpv = IrsNpvForRateShock(ws, shockedMonths, DV01_BUMP_RATE)
    downNpv = IrsNpvForRateShock(ws, shockedMonths, -DV01_BUMP_RATE)

    IRS_TENOR_DV01 = ((baseNpv - upNpv) + (downNpv - baseNpv)) / 2#
    Exit Function

Fail:
    IRS_TENOR_DV01 = CVErr(xlErrValue)
End Function

Private Function IrsNpvForRateShock(ByVal ws As Worksheet, ByVal shockedMonths As Long, _
                                    ByVal shockRate As Double) As Double
    Dim curveDates() As Date
    Dim curveZcrs() As Double
    Dim curvePointCount As Long

    BuildShockedCurve ws, shockedMonths, shockRate, curveDates, curveZcrs, curvePointCount

    Dim notional As Double
    Dim dayBasis As Double
    Dim fixedRate As Double
    Dim baseDate As Date
    Dim cashflowCutoffDate As Date

    notional = CDbl(ws.Cells(INPUT_VALUE_ROW, COL_NOTIONAL).value)
    dayBasis = CDbl(ws.Cells(INPUT_VALUE_ROW, COL_DAY_BASIS).value)
    fixedRate = CDbl(ws.Cells(INPUT_VALUE_ROW, COL_FIXED_RATE).value)
    baseDate = CDate(ws.Cells(INPUT_VALUE_ROW, COL_VALUATION_DATE).value)
    cashflowCutoffDate = CDate(ws.Range(CASHFLOW_CUTOFF_CELL).value)

    Dim c As Long
    Dim lastCol As Long
    Dim startDate As Date
    Dim payDate As Date
    Dim accrualDays As Double
    Dim accrualFactor As Double
    Dim payDf As Double
    Dim startDf As Double
    Dim couponRate As Double
    Dim fixedCoupon As Double
    Dim floatCoupon As Double

    lastCol = LastScheduleColumn(ws)

    For c = SCHEDULE_FIRST_COL To lastCol
        If IsDate(ws.Cells(SCHED_ROW_START, c).value) And IsDate(ws.Cells(SCHED_ROW_END, c).value) Then
            startDate = CDate(ws.Cells(SCHED_ROW_START, c).value)
            payDate = CDate(ws.Cells(SCHED_ROW_END, c).value)

            If payDate >= cashflowCutoffDate Then
                accrualDays = CDbl(payDate - startDate)
                If accrualDays > 0# Then
                    accrualFactor = accrualDays / dayBasis
                    payDf = ShockedDailyDf(payDate, baseDate, dayBasis, curveDates, curveZcrs, curvePointCount)
                    fixedCoupon = notional * fixedRate / 100# * accrualFactor

                    If startDate <= cashflowCutoffDate Then
                        couponRate = CdFixingRateForDate(ws, startDate)
                    Else
                        startDf = ShockedDailyDf(startDate, baseDate, dayBasis, curveDates, curveZcrs, curvePointCount)
                        couponRate = (startDf / payDf - 1#) / accrualFactor * 100#
                    End If

                    floatCoupon = notional * couponRate / 100# * accrualFactor
                    IrsNpvForRateShock = IrsNpvForRateShock + (floatCoupon - fixedCoupon) * payDf
                End If
            End If
        End If
    Next c
End Function

Private Sub BuildShockedCurve(ByVal ws As Worksheet, ByVal shockedMonths As Long, ByVal shockRate As Double, _
                              ByRef curveDates() As Date, ByRef curveZcrs() As Double, _
                              ByRef curvePointCount As Long)
    Dim keyMonths As Variant
    keyMonths = KeyTenorMonths()

    curvePointCount = CurrentCurvePointCount(ws)
    If curvePointCount < 2 Then
        Err.Raise vbObjectError + 111, , "Curve grid is not available for DV01."
    End If

    Dim keyRates As Object
    Set keyRates = ReadDisplayedCurveKeyRates(ws, keyMonths, curvePointCount)

    If Not keyRates.Exists(CStr(shockedMonths)) Then
        Err.Raise vbObjectError + 110, , "DV01 tenor is not a key par-rate tenor: " & TenorLabel(shockedMonths)
    End If

    keyRates(CStr(shockedMonths)) = CDbl(keyRates(CStr(shockedMonths))) + shockRate

    Dim curveDays() As Double
    Dim interpRates() As Double
    Dim accrualDays() As Double
    Dim curveDfs() As Double

    ReDim curveDates(1 To curvePointCount)
    ReDim curveDays(1 To curvePointCount)
    ReDim interpRates(1 To curvePointCount)
    ReDim accrualDays(1 To curvePointCount)
    ReDim curveDfs(1 To curvePointCount)
    ReDim curveZcrs(1 To curvePointCount)

    Dim i As Long
    Dim r As Long

    For i = 1 To curvePointCount
        r = OUTPUT_FIRST_ROW + i - 1
        curveDates(i) = CDate(ws.Cells(r, "B").value)
        curveDays(i) = CDbl(ws.Cells(r, "D").value)
    Next i

    Dim months As Long
    Dim lowerMonths As Long
    Dim upperMonths As Long
    Dim lowerIndex As Long
    Dim upperIndex As Long

    For i = 1 To curvePointCount
        months = (i - 1) * 3

        If keyRates.Exists(CStr(months)) Then
            interpRates(i) = CDbl(keyRates(CStr(months)))
        Else
            FindInterpolationBounds months, keyMonths, lowerMonths, upperMonths
            lowerIndex = lowerMonths \ 3 + 1
            upperIndex = upperMonths \ 3 + 1

            If upperIndex > curvePointCount Then
                Err.Raise vbObjectError + 112, , "Curve grid does not include DV01 interpolation upper tenor."
            End If

            interpRates(i) = (CDbl(keyRates(CStr(upperMonths))) - CDbl(keyRates(CStr(lowerMonths)))) / _
                             (curveDays(upperIndex) - curveDays(lowerIndex)) * _
                             (curveDays(i) - curveDays(lowerIndex)) + CDbl(keyRates(CStr(lowerMonths)))
        End If
    Next i

    Dim dayBasis As Double
    Dim sumProduct As Double
    Dim j As Long

    dayBasis = CDbl(ws.Cells(INPUT_VALUE_ROW, COL_DAY_BASIS).value)
    curveDfs(1) = 1#
    curveZcrs(1) = interpRates(1)

    For i = 2 To curvePointCount
        months = (i - 1) * 3
        accrualDays(i) = curveDays(i) - curveDays(i - 1)

        If months = 3 Then
            curveDfs(i) = 1# / (1# + interpRates(i) / 100# * accrualDays(i) / dayBasis)
        Else
            sumProduct = 0#
            For j = 2 To i - 1
                sumProduct = sumProduct + curveDfs(j) * accrualDays(j)
            Next j

            curveDfs(i) = (dayBasis * 100# - interpRates(i) * sumProduct) / _
                          (dayBasis * 100# + accrualDays(i) * interpRates(i))
        End If

        If curveDfs(i) <= 0# Or curveDays(i) <= 0# Then
            Err.Raise vbObjectError + 113, , "DV01 shocked curve produced invalid DF."
        End If

        curveZcrs(i) = -Log(curveDfs(i)) * dayBasis / curveDays(i) * 100#
    Next i
End Sub

Private Function ShockedDailyDf(ByVal d As Date, ByVal baseDate As Date, ByVal dayBasis As Double, _
                                ByRef curveDates() As Date, ByRef curveZcrs() As Double, _
                                ByVal curvePointCount As Long) As Double
    If d = baseDate Then
        ShockedDailyDf = 1#
        Exit Function
    End If

    If d < baseDate Then
        Err.Raise vbObjectError + 114, , "DV01 target date is before valuation date."
    End If

    Dim i As Long
    Dim alpha As Double
    Dim zcr As Double

    For i = 1 To curvePointCount - 1
        If d >= curveDates(i) And d <= curveDates(i + 1) Then
            alpha = CDbl(d - curveDates(i)) / CDbl(curveDates(i + 1) - curveDates(i))
            zcr = curveZcrs(i) + (curveZcrs(i + 1) - curveZcrs(i)) * alpha
            ShockedDailyDf = Exp(-zcr / 100# * CDbl(d - baseDate) / dayBasis)
            Exit Function
        End If
    Next i

    Err.Raise vbObjectError + 115, , "DV01 target date is outside curve grid."
End Function

Private Function CdFixingRateForDate(ByVal sourceWs As Worksheet, ByVal fixingDate As Date) As Double
    Dim ws As Worksheet
    Set ws = sourceWs.Parent.Worksheets(CD_FIXINGS_SHEET)

    Dim r As Long
    Dim lastRow As Long
    lastRow = ws.Cells(ws.Rows.Count, "A").End(xlUp).Row

    For r = 2 To lastRow
        If IsDate(ws.Cells(r, "A").value) Then
            If CLng(CDate(ws.Cells(r, "A").value)) = CLng(fixingDate) Then
                If IsNumeric(ws.Cells(r, "B").value) Then
                    CdFixingRateForDate = CDbl(ws.Cells(r, "B").value)
                    Exit Function
                End If
            End If
        End If
    Next r

    Err.Raise vbObjectError + 116, , "CD fixing not found for DV01: " & Format$(fixingDate, DATE_FORMAT)
End Function

Private Function CurrentCurvePointCount(ByVal ws As Worksheet) As Long
    Dim r As Long
    r = OUTPUT_FIRST_ROW

    Do While r <= OUTPUT_FIRST_ROW + MAX_QUARTERS
        If Not IsDate(ws.Cells(r, "B").value) Then Exit Do
        CurrentCurvePointCount = CurrentCurvePointCount + 1
        r = r + 1
    Loop
End Function

Private Function ReadDisplayedCurveKeyRates(ByVal ws As Worksheet, ByVal keyMonths As Variant, _
                                            ByVal curvePointCount As Long) As Object
    Dim rates As Object
    Set rates = CreateObject("Scripting.Dictionary")

    Dim i As Long
    Dim months As Long
    Dim pointIndex As Long
    Dim r As Long

    For i = LBound(keyMonths) To UBound(keyMonths)
        months = CLng(keyMonths(i))
        pointIndex = months \ 3 + 1

        If pointIndex <= curvePointCount Then
            r = OUTPUT_FIRST_ROW + pointIndex - 1
            If IsNumeric(ws.Cells(r, "C").value) Then
                rates(CStr(months)) = CDbl(ws.Cells(r, "C").value)
            End If
        End If
    Next i

    Set ReadDisplayedCurveKeyRates = rates
End Function

Private Function LastScheduleColumn(ByVal ws As Worksheet) As Long
    LastScheduleColumn = ws.Cells(SCHED_ROW_END, ws.Columns.Count).End(xlToLeft).Column

    If LastScheduleColumn < SCHEDULE_FIRST_COL Then
        LastScheduleColumn = SCHEDULE_FIRST_COL - 1
    End If
End Function

Private Function TryParseTenorMonths(ByVal tenor As Variant, ByRef months As Long) As Boolean
    On Error GoTo Fail

    Dim s As String
    s = UCase$(Trim$(CStr(tenor)))

    If IsNumeric(s) Then
        months = CLng(s)
    ElseIf s = "CALL" Then
        months = 0
    ElseIf s = "CD" Then
        months = 3
    ElseIf Right$(s, 1) = "Y" Then
        months = CLng(Left$(s, Len(s) - 1)) * 12
    ElseIf Right$(s, 1) = "M" Then
        months = CLng(Left$(s, Len(s) - 1))
    Else
        Exit Function
    End If

    TryParseTenorMonths = (months >= 0)
    Exit Function

Fail:
    TryParseTenorMonths = False
End Function

Public Function IRS_DAILY_DF(ByVal targetDate As Variant, Optional ByVal sheetName As String = "") As Variant
    On Error GoTo Fail
    Application.Volatile True

    If Not IsDate(targetDate) Then
        IRS_DAILY_DF = CVErr(xlErrValue)
        Exit Function
    End If

    Dim ws As Worksheet
    If Len(sheetName) > 0 Then
        Set ws = IrsTargetWorkbook().Worksheets(sheetName)
    ElseIf TypeName(Application.Caller) = "Range" Then
        Set ws = Application.Caller.Worksheet
    Else
        Set ws = ActiveSheet
    End If

    Dim d As Date
    d = CDate(targetDate)

    Dim baseDate As Date
    baseDate = CDate(ws.Cells(INPUT_VALUE_ROW, COL_VALUATION_DATE).value)

    If d = baseDate Then
        IRS_DAILY_DF = 1#
        Exit Function
    End If

    If d < baseDate Then
        IRS_DAILY_DF = CVErr(xlErrNA)
        Exit Function
    End If

    Dim r As Long
    Dim d0 As Date
    Dim d1 As Date
    Dim zcr0 As Double
    Dim zcr1 As Double
    Dim zcr As Double
    Dim alpha As Double
    Dim daysFromBase As Double
    Dim dayBasis As Double

    dayBasis = CDbl(ws.Cells(INPUT_VALUE_ROW, COL_DAY_BASIS).value)

    For r = OUTPUT_FIRST_ROW To OUTPUT_FIRST_ROW + MAX_QUARTERS - 1
        If IsDate(ws.Cells(r, "B").value) And IsDate(ws.Cells(r + 1, "B").value) Then
            d0 = CDate(ws.Cells(r, "B").value)
            d1 = CDate(ws.Cells(r + 1, "B").value)

            If d >= d0 And d <= d1 Then
                zcr0 = CDbl(ws.Cells(r, "H").value)
                zcr1 = CDbl(ws.Cells(r + 1, "H").value)
                alpha = CDbl(d - d0) / CDbl(d1 - d0)
                zcr = zcr0 + (zcr1 - zcr0) * alpha
                daysFromBase = CDbl(d - baseDate)
                IRS_DAILY_DF = Exp(-zcr / 100# * daysFromBase / dayBasis)
                Exit Function
            End If
        End If
    Next r

    IRS_DAILY_DF = CVErr(xlErrNA)
    Exit Function

Fail:
    IRS_DAILY_DF = CVErr(xlErrValue)
End Function

Public Function IRS_DAILY_DF_LOG_LINEAR(ByVal targetDate As Variant, Optional ByVal sheetName As String = "") As Variant
    On Error GoTo Fail
    Application.Volatile True

    If Not IsDate(targetDate) Then
        IRS_DAILY_DF_LOG_LINEAR = CVErr(xlErrValue)
        Exit Function
    End If

    Dim ws As Worksheet
    If Len(sheetName) > 0 Then
        Set ws = IrsTargetWorkbook().Worksheets(sheetName)
    ElseIf TypeName(Application.Caller) = "Range" Then
        Set ws = Application.Caller.Worksheet
    Else
        Set ws = ActiveSheet
    End If

    Dim d As Date
    d = CDate(targetDate)

    Dim baseDate As Date
    baseDate = CDate(ws.Cells(INPUT_VALUE_ROW, COL_VALUATION_DATE).value)

    If d = baseDate Then
        IRS_DAILY_DF_LOG_LINEAR = 1#
        Exit Function
    End If

    If d < baseDate Then
        IRS_DAILY_DF_LOG_LINEAR = CVErr(xlErrNA)
        Exit Function
    End If

    Dim r As Long
    Dim d0 As Date
    Dim d1 As Date
    Dim df0 As Double
    Dim df1 As Double
    Dim alpha As Double

    For r = OUTPUT_FIRST_ROW To OUTPUT_FIRST_ROW + MAX_QUARTERS - 1
        If IsDate(ws.Cells(r, "B").value) And IsDate(ws.Cells(r + 1, "B").value) Then
            d0 = CDate(ws.Cells(r, "B").value)
            d1 = CDate(ws.Cells(r + 1, "B").value)

            If d = d0 Then
                IRS_DAILY_DF_LOG_LINEAR = CDbl(ws.Cells(r, "G").value)
                Exit Function
            End If

            If d > d0 And d <= d1 Then
                df0 = CDbl(ws.Cells(r, "G").value)
                df1 = CDbl(ws.Cells(r + 1, "G").value)
                alpha = CDbl(d - d0) / CDbl(d1 - d0)
                IRS_DAILY_DF_LOG_LINEAR = Exp(Log(df0) + (Log(df1) - Log(df0)) * alpha)
                Exit Function
            End If
        End If
    Next r

    IRS_DAILY_DF_LOG_LINEAR = CVErr(xlErrNA)
    Exit Function

Fail:
    IRS_DAILY_DF_LOG_LINEAR = CVErr(xlErrValue)
End Function

Private Sub FormatIRSNpvSheet(ByVal ws As Worksheet, ByVal couponCount As Long, ByVal curveQuarterCount As Long)
    Dim lastScheduleCol As Long
    If couponCount > 0 Then
        lastScheduleCol = SCHEDULE_FIRST_COL + couponCount - 1
    Else
        lastScheduleCol = 1
    End If

    With ws.Range(ws.Cells(SCHED_ROW_START, "A"), ws.Cells(SCHED_ROW_NET_PV, lastScheduleCol))
        .Borders.LineStyle = xlContinuous
        .HorizontalAlignment = xlCenter
        .VerticalAlignment = xlCenter
    End With

    With ws.Range(ws.Cells(SCHED_ROW_START, "A"), ws.Cells(SCHED_ROW_NET_PV, "A"))
        .Interior.Color = RGB(221, 235, 247)
        .Font.Bold = True
    End With

    If couponCount > 0 Then
        ws.Range(ws.Cells(SCHED_ROW_START, SCHEDULE_FIRST_COL), ws.Cells(SCHED_ROW_END, lastScheduleCol)).NumberFormat = DATE_FORMAT
        ws.Range(ws.Cells(SCHED_ROW_DAYS, SCHEDULE_FIRST_COL), ws.Cells(SCHED_ROW_DAYS, lastScheduleCol)).NumberFormat = "0"
        ws.Range(ws.Cells(SCHED_ROW_ACCRUAL, SCHEDULE_FIRST_COL), ws.Cells(SCHED_ROW_ACCRUAL, lastScheduleCol)).NumberFormat = RATE_FORMAT
        ws.Range(ws.Cells(SCHED_ROW_FORWARD, SCHEDULE_FIRST_COL), ws.Cells(SCHED_ROW_COUPON_RATE, lastScheduleCol)).NumberFormat = RATE_FORMAT
        ws.Range(ws.Cells(SCHED_ROW_PAY_DF, SCHEDULE_FIRST_COL), ws.Cells(SCHED_ROW_PAY_DF, lastScheduleCol)).NumberFormat = RATE_FORMAT
        ws.Range(ws.Cells(SCHED_ROW_FIXED_COUPON, SCHEDULE_FIRST_COL), ws.Cells(SCHED_ROW_NET_PV, lastScheduleCol)).NumberFormat = AMOUNT_FORMAT
    End If

    With ws.Range(ws.Cells(SUMMARY_ROW, "A"), ws.Cells(SUMMARY_ROW + 2, "L"))
        .Borders.LineStyle = xlContinuous
    End With

    ws.Range(ws.Cells(SUMMARY_ROW, "B"), ws.Cells(SUMMARY_ROW, "F")).NumberFormat = AMOUNT_FORMAT
    ws.Cells(SUMMARY_ROW + 1, "J").NumberFormat = DATE_FORMAT
    ws.Range(ws.Cells(SUMMARY_ROW + 1, "K"), ws.Cells(SUMMARY_ROW + 1, "L")).NumberFormat = RATE_FORMAT

    Dim lastCurveRow As Long
    lastCurveRow = OUTPUT_FIRST_ROW + curveQuarterCount

    With ws.Range(ws.Cells(OUTPUT_HEADER_ROW, "A"), ws.Cells(OUTPUT_HEADER_ROW, "I"))
        .Interior.Color = vbYellow
        .HorizontalAlignment = xlCenter
        .VerticalAlignment = xlCenter
        .Borders.LineStyle = xlContinuous
        .Font.Bold = True
    End With

    ws.Range(ws.Cells(OUTPUT_FIRST_ROW, "A"), ws.Cells(lastCurveRow, "A")).HorizontalAlignment = xlLeft
    ws.Range(ws.Cells(OUTPUT_FIRST_ROW, "B"), ws.Cells(lastCurveRow, "B")).NumberFormat = DATE_FORMAT
    ws.Range(ws.Cells(OUTPUT_FIRST_ROW, "C"), ws.Cells(lastCurveRow, "C")).NumberFormat = RATE_FORMAT
    ws.Range(ws.Cells(OUTPUT_FIRST_ROW, "D"), ws.Cells(lastCurveRow, "D")).NumberFormat = "0"
    ws.Range(ws.Cells(OUTPUT_FIRST_ROW, "E"), ws.Cells(lastCurveRow, "E")).NumberFormat = RATE_FORMAT
    ws.Range(ws.Cells(OUTPUT_FIRST_ROW, "F"), ws.Cells(lastCurveRow, "F")).NumberFormat = "0"
    ws.Range(ws.Cells(OUTPUT_FIRST_ROW, "G"), ws.Cells(lastCurveRow, "H")).NumberFormat = RATE_FORMAT
    ws.Range(ws.Cells(OUTPUT_FIRST_ROW, "I"), ws.Cells(lastCurveRow, "I")).NumberFormat = AMOUNT_FORMAT
    ws.Range(ws.Cells(OUTPUT_HEADER_ROW, "A"), ws.Cells(lastCurveRow, "I")).Borders.LineStyle = xlContinuous

    Dim r As Long
    For r = OUTPUT_FIRST_ROW To lastCurveRow
        If Len(ws.Cells(r, "C").value) > 0 Then
            ws.Cells(r, "A").Interior.Color = vbYellow
        End If
    Next r

    ws.Columns("A:CC").AutoFit
End Sub

Private Sub WriteNonBusinessLog(ByVal ws As Worksheet, ByVal nonBizRows As Collection, ByVal startRow As Long)
    If nonBizRows.Count = 0 Then Exit Sub

    ws.Cells(startRow, "A").value = "Non-business day log"
    ws.Range(ws.Cells(startRow + 1, "A"), ws.Cells(startRow + 1, "D")).value = Array("Item", "Original Date", "Adjusted Date", "Reason")

    Dim i As Long
    Dim item As Variant
    For i = 1 To nonBizRows.Count
        item = nonBizRows(i)
        ws.Cells(startRow + 1 + i, "A").value = item(0)
        ws.Cells(startRow + 1 + i, "B").value = item(1)
        ws.Cells(startRow + 1 + i, "C").value = item(2)
        ws.Cells(startRow + 1 + i, "D").value = item(3)
    Next i

    With ws.Range(ws.Cells(startRow + 1, "A"), ws.Cells(startRow + 1, "D"))
        .Interior.Color = vbYellow
        .HorizontalAlignment = xlCenter
        .Borders.LineStyle = xlContinuous
    End With

    ws.Range(ws.Cells(startRow + 2, "B"), ws.Cells(startRow + 1 + nonBizRows.Count, "C")).NumberFormat = DATE_FORMAT
    ws.Range(ws.Cells(startRow, "A"), ws.Cells(startRow + 1 + nonBizRows.Count, "D")).Borders.LineStyle = xlContinuous
End Sub

Private Sub EnsureCdFixingsSheet()
    Dim ws As Worksheet
    Set ws = GetOrCreateSheet(CD_FIXINGS_SHEET)

    If Len(ws.Cells(1, "A").value) = 0 Then
        ws.Range("A1:C1").value = Array("Date", "CD91 Rate", "Source")
        ws.Range("A:A").NumberFormat = DATE_FORMAT
        ws.Range("B:B").NumberFormat = RATE_FORMAT
        ws.Columns("A:C").AutoFit
    End If
End Sub

Private Sub PrefetchMissingCdFixings(ByVal ws As Worksheet, ByVal couponCount As Long, ByVal cashflowCutoffDate As Date)
    Dim c As Long
    Dim lastCol As Long
    Dim fixingDate As Date
    Dim payDate As Date
    Dim fetchedRate As Variant

    lastCol = SCHEDULE_FIRST_COL + couponCount - 1

    For c = SCHEDULE_FIRST_COL To lastCol
        If IsDate(ws.Cells(SCHED_ROW_START, c).value) And IsDate(ws.Cells(SCHED_ROW_END, c).value) Then
            fixingDate = CDate(ws.Cells(SCHED_ROW_START, c).value)
            payDate = CDate(ws.Cells(SCHED_ROW_END, c).value)

            If payDate >= cashflowCutoffDate And fixingDate <= cashflowCutoffDate Then
                If Not CdFixingExists(fixingDate) Then
                    fetchedRate = FetchKofiaCd91Rate(fixingDate)
                    If IsNumeric(fetchedRate) Then
                        StoreCdFixing fixingDate, CDbl(fetchedRate), "KOFIA XMLSERVICES"
                    End If
                End If
            End If
        End If
    Next c
End Sub

Private Function CdFixingExists(ByVal fixingDate As Date) As Boolean
    Dim ws As Worksheet
    Set ws = GetOrCreateSheet(CD_FIXINGS_SHEET)

    Dim r As Long
    Dim lastRow As Long
    lastRow = ws.Cells(ws.Rows.Count, "A").End(xlUp).Row

    For r = 2 To lastRow
        If IsDate(ws.Cells(r, "A").value) Then
            If CLng(CDate(ws.Cells(r, "A").value)) = CLng(fixingDate) Then
                If IsNumeric(ws.Cells(r, "B").value) Then
                    CdFixingExists = True
                    Exit Function
                End If
            End If
        End If
    Next r
End Function

Private Sub StoreCdFixing(ByVal fixingDate As Date, ByVal rate As Double, ByVal source As String)
    Dim ws As Worksheet
    Set ws = GetOrCreateSheet(CD_FIXINGS_SHEET)

    Dim r As Long
    Dim lastRow As Long
    lastRow = ws.Cells(ws.Rows.Count, "A").End(xlUp).Row

    For r = 2 To lastRow
        If IsDate(ws.Cells(r, "A").value) Then
            If CLng(CDate(ws.Cells(r, "A").value)) = CLng(fixingDate) Then
                ws.Cells(r, "B").value = rate
                ws.Cells(r, "C").value = source
                Exit Sub
            End If
        End If
    Next r

    r = lastRow + 1
    ws.Cells(r, "A").value = fixingDate
    ws.Cells(r, "B").value = rate
    ws.Cells(r, "C").value = source

    ws.Range("A:A").NumberFormat = DATE_FORMAT
    ws.Range("B:B").NumberFormat = RATE_FORMAT
    ws.Columns("A:C").AutoFit
End Sub

Private Function FetchKofiaCd91Rate(ByVal fixingDate As Date) As Variant
    On Error GoTo Fail

    Dim ymd As String
    ymd = Format$(fixingDate, "yyyymmdd")

    Dim xmlBody As String
    xmlBody = "<?xml version=""1.0"" encoding=""utf-8""?><message>" & _
              "<proframeHeader><pfmAppName>BIS-KOFIABOND</pfmAppName>" & _
              "<pfmSvcName>BISLastAskPrcROPSrchSO</pfmSvcName><pfmFnName>listTrm</pfmFnName>" & _
              "</proframeHeader><systemHeader></systemHeader><BISComDspDatDTO>" & _
              "<val1>DD</val1><val2>" & ymd & "</val2><val3>" & ymd & "</val3>" & _
              "<val4>1530</val4><val5>4000</val5></BISComDspDatDTO></message>"

    Dim responseText As String
    responseText = FetchKofiaXml("https://www.kofiabond.or.kr/proframeWeb/XMLSERVICES/", xmlBody)

    Dim re As Object
    Dim m As Object
    Set re = CreateObject("VBScript.RegExp")
    re.Global = False
    re.IgnoreCase = True
    re.Pattern = "<BISComDspDatDTO>[\s\S]*?<val1>" & Format$(fixingDate, "yyyy-mm-dd") & "</val1>[\s\S]*?<val2>([0-9.]+)</val2>"

    If re.Test(responseText) Then
        Set m = re.Execute(responseText)(0)
        FetchKofiaCd91Rate = CDbl(m.SubMatches(0))
        Exit Function
    End If

    FetchKofiaCd91Rate = Empty
    Exit Function

Fail:
    FetchKofiaCd91Rate = Empty
End Function

Private Function FetchKofiaXml(ByVal url As String, ByVal body As String) As String
    Dim http As Object
    Set http = CreateObject("MSXML2.ServerXMLHTTP.6.0")

    http.setTimeouts 5000, 5000, 15000, 15000
    http.Open "POST", url, False
    http.setRequestHeader "User-Agent", "Mozilla/5.0"
    http.setRequestHeader "Content-Type", "text/xml; charset=utf-8"
    http.Send body

    If http.Status <> 200 Then
        Err.Raise vbObjectError + 310, , "KOFIA HTTP error: " & http.Status
    End If

    FetchKofiaXml = http.responseText
End Function

Private Sub CreateOrUpdateRefreshButton(ByVal ws As Worksheet)
    Dim shp As Shape

    On Error Resume Next
    Set shp = ws.Shapes(REFRESH_BUTTON_NAME)
    On Error GoTo 0

    If shp Is Nothing Then
        Set shp = ws.Shapes.AddFormControl(xlButtonControl, ws.Range("Y2").Left, ws.Range("Y2").Top, _
                                           ws.Range("Y2:Z3").Width, ws.Range("Y2:Z3").Height)
        shp.name = REFRESH_BUTTON_NAME
    End If

    With shp
        .Left = ws.Range("Y2").Left
        .Top = ws.Range("Y2").Top
        .Width = ws.Range("Y2:Z3").Width
        .Height = ws.Range("Y2:Z3").Height
        .OnAction = "'" & WorkbookNameForOnAction(ThisWorkbook) & "'!RefreshIRSNpvTool"
        .TextFrame.Characters.Text = "REFRESH"
        .Placement = xlMoveAndSize
    End With

    On Error Resume Next
    Set shp = Nothing
    Set shp = ws.Shapes(CALENDAR_UPDATE_BUTTON_NAME)
    On Error GoTo 0

    If shp Is Nothing Then
        Set shp = ws.Shapes.AddFormControl(xlButtonControl, ws.Range("Y5").Left, ws.Range("Y5").Top, _
                                           ws.Range("Y5:Z6").Width, ws.Range("Y5:Z6").Height)
        shp.name = CALENDAR_UPDATE_BUTTON_NAME
    End If

    With shp
        .Left = ws.Range("Y5").Left
        .Top = ws.Range("Y5").Top
        .Width = ws.Range("Y5:Z6").Width
        .Height = ws.Range("Y5:Z6").Height
        .OnAction = "'" & WorkbookNameForOnAction(ThisWorkbook) & "'!UpdateIrsCalendarCache2020To2040"
        .TextFrame.Characters.Text = "CALENDAR UPDATE"
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

Private Sub FindInterpolationBounds(ByVal months As Long, ByVal keyMonths As Variant, _
                                    ByRef lowerMonths As Long, ByRef upperMonths As Long)
    Dim i As Long

    For i = LBound(keyMonths) To UBound(keyMonths) - 1
        If CLng(keyMonths(i)) < months And months < CLng(keyMonths(i + 1)) Then
            lowerMonths = CLng(keyMonths(i))
            upperMonths = CLng(keyMonths(i + 1))
            Exit Sub
        End If
    Next i

    Err.Raise vbObjectError + 100, , "Interpolation bounds not found: " & CStr(months) & "M"
End Sub

Private Sub UpdateIrsCalendar(ByVal holidays As Object, ByVal firstYear As Long, ByVal lastYear As Long)
    holidays.RemoveAll

    If LoadCalendarSheet(holidays, firstYear, lastYear) Then
        AddManualHolidays holidays
        Exit Sub
    End If

    Err.Raise vbObjectError + 200, , "IRS_Calendar cache does not cover " & CStr(firstYear) & "-" & CStr(lastYear) & _
                                    ". Press CALENDAR UPDATE before Refresh. No fallback calendar was used."
End Sub

Public Sub UpdateIrsCalendarCache2020To2040()
    On Error GoTo Fail

    Dim ws As Worksheet

    SetIrsStep "Set active sheet for calendar update"
    Set ws = ActiveSheet
    Set gIrsTargetWorkbook = ws.Parent

    SetIrsStep "Check workbook and sheet protection"
    EnsureWritableIrsTarget ws

    SetIrsStep "Disable Excel UI updates"
    Application.ScreenUpdating = False
    Application.EnableEvents = False

    Dim covered As Object
    Set covered = CreateObject("Scripting.Dictionary")

    Dim holidays As Object
    Set holidays = CreateObject("Scripting.Dictionary")

    Dim y As Long
    Dim ok As Boolean

    For y = CALENDAR_UPDATE_FIRST_YEAR To CALENDAR_UPDATE_LAST_YEAR
        SetIrsStep "Fetch holiday calendar " & CStr(y)
        ok = False

        If AddNagerHolidays(y, holidays) Then ok = True

        If y <= Year(Date) + KRX_LOOKAHEAD_YEARS Then
            If AddKrxHolidays(y, holidays) Then ok = True
        End If

        If ok Then covered(CStr(y)) = True
    Next y

    If Not AllYearsCovered(covered, CALENDAR_UPDATE_FIRST_YEAR, CALENDAR_UPDATE_LAST_YEAR) Then
        Err.Raise vbObjectError + 201, , "Calendar update failed. IRS_Calendar was not overwritten."
    End If

    SetIrsStep "Write IRS_Calendar sheet"
    WriteCalendarSheet holidays

    SetIrsStep "Setup IRS NPV sheet"
    SetupIRSNpvSheet ws

    MsgBox "IRS_Calendar updated for " & CStr(CALENDAR_UPDATE_FIRST_YEAR) & "-" & CStr(CALENDAR_UPDATE_LAST_YEAR) & ".", vbInformation

CleanExit:
    Application.EnableEvents = True
    Application.ScreenUpdating = True
    Set gIrsTargetWorkbook = Nothing
    Exit Sub

Fail:
    Dim errNo As Long
    Dim errDesc As String
    Dim errSource As String
    Dim errLine As Long

    errNo = Err.Number
    errDesc = Err.Description
    errSource = Err.Source
    errLine = Erl

    Application.EnableEvents = True
    Application.ScreenUpdating = True

    MsgBox BuildIrsErrorMessage("Calendar update failed", errNo, errDesc, errSource, errLine, ws), vbCritical
    Set gIrsTargetWorkbook = Nothing
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
        If InStr(1, reason, "year", vbTextCompare) > 0 Or _
           InStr(1, reason, "end", vbTextCompare) > 0 Or _
           InStr(1, reason, KoreanYearEndLabel(), vbTextCompare) > 0 Or _
           InStr(1, reason, KoreanMarketCloseLabel(), vbTextCompare) > 0 Then
            IsIrsRelevantKrxHoliday = False
        End If
    End If
End Function

Private Sub AddManualHolidays(ByVal holidays As Object)
    On Error Resume Next
    Dim ws As Worksheet
    Set ws = IrsTargetWorkbook().Worksheets("IRS_ManualHolidays")
    On Error GoTo 0

    If ws Is Nothing Then Exit Sub

    Dim r As Long
    Dim lastRow As Long
    lastRow = ws.Cells(ws.Rows.Count, "A").End(xlUp).Row

    For r = 2 To lastRow
        If IsDate(ws.Cells(r, "A").value) Then
            AddHoliday holidays, CDate(ws.Cells(r, "A").value), CStr(ws.Cells(r, "B").value), "Manual"
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

    If Weekday(d, vbMonday) > 5 Then reason = "Weekend"

    If holidays.Exists(key) Then
        If Len(reason) > 0 Then reason = reason & " / "
        reason = reason & CStr(holidays(key))
    End If

    If Len(reason) = 0 Then reason = "Non-business day"
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
        Err.Raise vbObjectError + 300, , "HTTP error: " & http.Status & " / " & url
    End If

    FetchText = http.responseText
End Function

Private Function ParseIsoDate(ByVal s As String) As Date
    ParseIsoDate = DateSerial(CInt(Left$(s, 4)), CInt(mid$(s, 6, 2)), CInt(Right$(s, 2)))
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
        ch = mid$(s, i, 1)
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
    ws.Range("A1:D1").value = Array("Date", "Name(Source)", "Key", "UpdatedAt")

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
        ws.Cells(r, 1).value = DateSerial(CInt(Left$(k, 4)), CInt(mid$(k, 5, 2)), CInt(Right$(k, 2)))
        ws.Cells(r, 2).value = holidays(k)
        ws.Cells(r, 3).value = CStr(k)
        ws.Cells(r, 4).value = Now
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
    Set ws = IrsTargetWorkbook().Worksheets("IRS_Calendar")

    Dim covered As Object
    Set covered = CreateObject("Scripting.Dictionary")

    Dim r As Long
    Dim lastRow As Long
    Dim d As Date
    lastRow = ws.Cells(ws.Rows.Count, "A").End(xlUp).Row

    For r = 2 To lastRow
        If IsDate(ws.Cells(r, "A").value) Then
            d = CDate(ws.Cells(r, "A").value)

            If Year(d) >= firstYear And Year(d) <= lastYear Then
                holidays(Format$(d, "yyyymmdd")) = CStr(ws.Cells(r, "B").value) & " [Cached]"
                covered(CStr(Year(d))) = True
            End If
        End If
    Next r

    LoadCalendarSheet = AllYearsCovered(covered, firstYear, lastYear)
    Exit Function

Fail:
    LoadCalendarSheet = False
End Function

Private Sub SetIrsStep(ByVal stepName As String)
    gIrsCurrentStep = stepName
    Debug.Print Format$(Now, "yyyy-mm-dd hh:nn:ss") & " | IRS NPV | " & stepName
End Sub

Private Sub EnsureWritableIrsTarget(ByVal ws As Worksheet)
    If ws Is Nothing Then
        Err.Raise vbObjectError + 10, , "No active worksheet was found."
    End If

    If ws.ProtectContents Then
        Err.Raise vbObjectError + 11, , "Active sheet is protected: " & ws.Name & ". Unprotect the sheet before Refresh."
    End If

    If ws.Parent.ProtectStructure Then
        Err.Raise vbObjectError + 12, , "Workbook structure is protected: " & ws.Parent.Name & ". Unprotect workbook structure before Refresh."
    End If
End Sub

Private Function IrsTargetWorkbook() As Workbook
    If Not gIrsTargetWorkbook Is Nothing Then
        Set IrsTargetWorkbook = gIrsTargetWorkbook
    ElseIf TypeName(Application.Caller) = "Range" Then
        Set IrsTargetWorkbook = Application.Caller.Worksheet.Parent
    ElseIf Not ActiveWorkbook Is Nothing Then
        Set IrsTargetWorkbook = ActiveWorkbook
    Else
        Set IrsTargetWorkbook = ThisWorkbook
    End If
End Function

Private Function WorkbookNameForOnAction(ByVal wb As Workbook) As String
    WorkbookNameForOnAction = Replace(wb.Name, "'", "''")
End Function

Private Function BuildIrsErrorMessage(ByVal title As String, ByVal errNo As Long, _
                                      ByVal errDesc As String, ByVal errSource As String, _
                                      ByVal errLine As Long, ByVal ws As Worksheet) As String
    On Error Resume Next

    Dim msg As String
    msg = title & vbCrLf & _
          "Step: " & IIf(Len(gIrsCurrentStep) > 0, gIrsCurrentStep, "(unknown)") & vbCrLf & _
          "Err.Number: " & CStr(errNo) & vbCrLf & _
          "Err.Description: " & errDesc

    If Len(errSource) > 0 Then msg = msg & vbCrLf & "Err.Source: " & errSource
    If errLine <> 0 Then msg = msg & vbCrLf & "Line: " & CStr(errLine)

    If Not ws Is Nothing Then
        msg = msg & vbCrLf & _
              "Active workbook: " & ws.Parent.Name & vbCrLf & _
              "Active sheet: " & ws.Name & vbCrLf & _
              "Sheet protected: " & CStr(ws.ProtectContents) & vbCrLf & _
              "Workbook structure protected: " & CStr(ws.Parent.ProtectStructure)
    End If

    msg = msg & vbCrLf & "Macro workbook: " & ThisWorkbook.Name
    BuildIrsErrorMessage = msg
End Function
Private Function GetOrCreateSheet(ByVal sheetName As String) As Worksheet
    Dim wb As Workbook
    Set wb = IrsTargetWorkbook()

    On Error Resume Next
    Set GetOrCreateSheet = wb.Worksheets(sheetName)
    On Error GoTo 0

    If GetOrCreateSheet Is Nothing Then
        If wb.ProtectStructure Then
            Err.Raise vbObjectError + 13, , "Workbook structure is protected: " & wb.Name & _
                                            ". Cannot create sheet " & sheetName & "."
        End If

        Set GetOrCreateSheet = wb.Worksheets.Add(After:=wb.Worksheets(wb.Worksheets.Count))
        GetOrCreateSheet.Name = sheetName
    End If
End Function
Private Function MinLong(ByVal a As Long, ByVal b As Long) As Long
    If a < b Then
        MinLong = a
    Else
        MinLong = b
    End If
End Function

Private Function MaxLong(ByVal a As Long, ByVal b As Long) As Long
    If a > b Then
        MaxLong = a
    Else
        MaxLong = b
    End If
End Function

Private Function KoreanValuationDatePlusOneBusinessDayLabel() As String
    KoreanValuationDatePlusOneBusinessDayLabel = _
        ChrW$(&HC0B0) & ChrW$(&HCD9C) & ChrW$(&HC77C) & " +1 " & _
        ChrW$(&HC601) & ChrW$(&HC5C5) & ChrW$(&HC77C)
End Function

Private Function KoreanValuationDatePlusTwoBusinessDaysLabel() As String
    KoreanValuationDatePlusTwoBusinessDaysLabel = _
        ChrW$(&HC0B0) & ChrW$(&HCD9C) & ChrW$(&HC77C) & "+2 " & _
        ChrW$(&HC601) & ChrW$(&HC5C5) & ChrW$(&HC77C)
End Function

Private Function KoreanYearEndLabel() As String
    KoreanYearEndLabel = ChrW$(&HC5F0) & ChrW$(&HB9D0)
End Function

Private Function KoreanMarketCloseLabel() As String
    KoreanMarketCloseLabel = ChrW$(&HD3D0) & ChrW$(&HC7A5)
End Function


