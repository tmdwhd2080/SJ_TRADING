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
Private Const SCHED_ROW_PAYMENT As Long = 7
Private Const SCHED_ROW_FIXING_DATE As Long = 8
Private Const SCHED_ROW_DAYS As Long = 9
Private Const SCHED_ROW_ACCRUAL As Long = 10
Private Const SCHED_ROW_FORWARD As Long = 11
Private Const SCHED_ROW_COUPON_RATE As Long = 12
Private Const SCHED_ROW_PAY_DF As Long = 13
Private Const SCHED_ROW_FIXED_COUPON As Long = 14
Private Const SCHED_ROW_FLOAT_COUPON As Long = 15
Private Const SCHED_ROW_FIXED_PV As Long = 16
Private Const SCHED_ROW_FLOAT_PV As Long = 17
Private Const SCHED_ROW_NET_PV As Long = 18

Private Const SUMMARY_ROW As Long = 23
Private Const CASHFLOW_CUTOFF_CELL As String = "$ZZ$1"
Private Const ACCRUAL_BASE_CELL As String = "$ZZ$2"
Private Const CASHFLOW_SETTLEMENT_LAG_BD As Long = 2
Private Const ACCRUAL_BASE_LAG_BD As Long = 1
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

Public Sub RefreshIRSNpvTool()
    On Error GoTo Fail

    Dim stepName As String
    stepName = "Start"

    Dim ws As Worksheet
    Set ws = ActiveSheet

    Application.ScreenUpdating = False
    Application.EnableEvents = False

    stepName = "Setup input headers"
    If ws.ProtectContents Then
        Err.Raise vbObjectError + 400, , "Active sheet is protected. Unprotect the input/output sheet before Refresh."
    End If
    SetupIRSNpvSheet ws, False

    stepName = "Ensure CD fixings sheet"
    EnsureCdFixingsSheet

    stepName = "Validate inputs"
    If Not ValidateInputs(ws) Then GoTo CleanExit

    stepName = "Read input dates"
    Dim effectiveDate As Date
    Dim maturityDate As Date
    Dim valuationDate As Date
    effectiveDate = CDate(ws.Cells(INPUT_VALUE_ROW, COL_EFFECTIVE_DATE).Value)
    maturityDate = CDate(ws.Cells(INPUT_VALUE_ROW, COL_MATURITY_DATE).Value)
    valuationDate = CDate(ws.Cells(INPUT_VALUE_ROW, COL_VALUATION_DATE).Value)

    Dim firstYear As Long
    Dim lastYear As Long
    firstYear = MinLong(Year(effectiveDate), Year(valuationDate))
    lastYear = MaxLong(Year(DateAdd("yyyy", 1, valuationDate)), Year(DateAdd("yyyy", 1, maturityDate)))

    Dim holidays As Object
    Set holidays = CreateObject("Scripting.Dictionary")

    stepName = "Load calendar cache"
    UpdateIrsCalendar holidays, firstYear, lastYear

    stepName = "Calculate cutoff and accrual base dates"
    Dim cashflowCutoffDate As Date
    Dim accrualBaseDate As Date
    cashflowCutoffDate = AddBusinessDays(valuationDate, CASHFLOW_SETTLEMENT_LAG_BD, holidays)
    accrualBaseDate = AddBusinessDays(valuationDate, ACCRUAL_BASE_LAG_BD, holidays)

    Dim keyMonths As Variant
    keyMonths = KeyTenorMonths()

    Dim keyRates As Object
    stepName = "Read market rates"
    Set keyRates = ReadKeyRates(ws, keyMonths)

    stepName = "Clear output area"
    ClearIrsOutputArea ws

    stepName = "Write internal cutoff dates"
    ws.Range(CASHFLOW_CUTOFF_CELL).Value = cashflowCutoffDate
    ws.Range(ACCRUAL_BASE_CELL).Value = accrualBaseDate

    Dim nonBizRows As Collection
    Set nonBizRows = New Collection

    Dim couponCount As Long
    stepName = "Write cashflow schedule"
    couponCount = WriteCashflowSchedule(ws, effectiveDate, maturityDate, valuationDate, cashflowCutoffDate, holidays, nonBizRows)

    stepName = "Prefetch CD fixings"
    PrefetchMissingCdFixings ws, couponCount, cashflowCutoffDate

    Dim curveQuarterCount As Long
    stepName = "Calculate curve horizon"
    curveQuarterCount = CurveQuarterCountThroughDate(valuationDate, MaxScheduledPaymentDate(ws, couponCount, maturityDate), holidays)

    stepName = "Write quarterly curve"
    WriteQuarterlyCurve ws, valuationDate, keyRates, keyMonths, holidays, nonBizRows, curveQuarterCount

    stepName = "Write NPV summary"
    WriteNpvSummary ws, couponCount

    stepName = "Write DF lookup box"
    WriteDfLookupBox ws

    stepName = "Write non-business day log"
    WriteNonBusinessLog ws, nonBizRows, OUTPUT_FIRST_ROW + curveQuarterCount + 3

    stepName = "Format output"
    FormatIRSNpvSheet ws, couponCount, curveQuarterCount

    stepName = "Calculate worksheet"
    ws.Calculate
    MsgBox "Done. Valuation Date = " & Format$(valuationDate, DATE_FORMAT), vbInformation

CleanExit:
    Application.EnableEvents = True
    Application.ScreenUpdating = True
    Exit Sub

Fail:
    Application.EnableEvents = True
    Application.ScreenUpdating = True
    MsgBox "IRS NPV refresh failed at [" & stepName & "]" & vbCrLf & _
           "Error " & CStr(Err.Number) & ": " & Err.Description, vbCritical
End Sub

Public Sub SetupIRSNpvSheet(ByVal ws As Worksheet, Optional ByVal updateButtons As Boolean = True)
    ws.Cells(INPUT_HEADER_ROW, COL_EFFECTIVE_DATE).Value = "Effective Date"
    ws.Cells(INPUT_HEADER_ROW, COL_MATURITY_DATE).Value = "Maturity Date"
    ws.Cells(INPUT_HEADER_ROW, COL_VALUATION_DATE).Value = KoreanValuationDatePlusOneBusinessDayLabel()
    ws.Cells(INPUT_HEADER_ROW, COL_NOTIONAL).Value = "Notional Amount"
    ws.Cells(INPUT_HEADER_ROW, COL_DAY_BASIS).Value = "Day Basis"
    ws.Cells(INPUT_HEADER_ROW, COL_FIXED_RATE).Value = "Fixed Rate"

    ws.Range(ws.Cells(INPUT_HEADER_ROW, RATE_INPUT_FIRST_COL), _
             ws.Cells(INPUT_HEADER_ROW, RATE_INPUT_FIRST_COL + UBound(KeyTenorNames()))).Value = KeyTenorNames()

    ws.Range("A3:C3").NumberFormat = DATE_FORMAT
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

    With ws.Range(ws.Cells(INPUT_VALUE_ROW, 1), _
                  ws.Cells(INPUT_VALUE_ROW, RATE_INPUT_FIRST_COL + UBound(KeyTenorNames())))
        .HorizontalAlignment = xlCenter
        .VerticalAlignment = xlCenter
        .Borders.LineStyle = xlContinuous
    End With

    If updateButtons Then CreateOrUpdateRefreshButton ws
End Sub

Private Function ValidateInputs(ByVal ws As Worksheet) As Boolean
    If Not IsDate(ws.Cells(INPUT_VALUE_ROW, COL_EFFECTIVE_DATE).Value) Then
        MsgBox "Enter Effective Date in A3.", vbExclamation
        Exit Function
    End If

    If Not IsDate(ws.Cells(INPUT_VALUE_ROW, COL_MATURITY_DATE).Value) Then
        MsgBox "Enter Maturity Date in B3.", vbExclamation
        Exit Function
    End If

    If Not IsDate(ws.Cells(INPUT_VALUE_ROW, COL_VALUATION_DATE).Value) Then
        MsgBox "Enter valuation date in C3.", vbExclamation
        Exit Function
    End If

    If CDate(ws.Cells(INPUT_VALUE_ROW, COL_EFFECTIVE_DATE).Value) >= _
       CDate(ws.Cells(INPUT_VALUE_ROW, COL_MATURITY_DATE).Value) Then
        MsgBox "Maturity Date must be later than Effective Date.", vbExclamation
        Exit Function
    End If

    If Not IsNumeric(ws.Cells(INPUT_VALUE_ROW, COL_NOTIONAL).Value) Then
        MsgBox "Enter Notional Amount in D3.", vbExclamation
        Exit Function
    End If

    If Not IsNumeric(ws.Cells(INPUT_VALUE_ROW, COL_DAY_BASIS).Value) Then
        MsgBox "Enter Day Basis in E3, such as 365 or 360.", vbExclamation
        Exit Function
    End If

    If CDbl(ws.Cells(INPUT_VALUE_ROW, COL_DAY_BASIS).Value) <= 0 Then
        MsgBox "Day Basis must be positive.", vbExclamation
        Exit Function
    End If

    If Not IsNumeric(ws.Cells(INPUT_VALUE_ROW, COL_FIXED_RATE).Value) Then
        MsgBox "Enter Fixed Rate in F3 as a percent number, such as 3.305.", vbExclamation
        Exit Function
    End If

    Dim keyNames As Variant
    keyNames = KeyTenorNames()

    Dim i As Long
    For i = LBound(keyNames) To UBound(keyNames)
        If Not IsNumeric(ws.Cells(INPUT_VALUE_ROW, RATE_INPUT_FIRST_COL + i).Value) Then
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
        rates(CStr(keyMonths(i))) = CDbl(ws.Cells(INPUT_VALUE_ROW, RATE_INPUT_FIRST_COL + i).Value)
    Next i

    Set ReadKeyRates = rates
End Function

Private Function WriteCashflowSchedule(ByVal ws As Worksheet, ByVal effectiveDate As Date, _
                                       ByVal maturityDate As Date, ByVal valuationDate As Date, _
                                       ByVal cashflowCutoffDate As Date, _
                                       ByVal holidays As Object, ByVal nonBizRows As Collection) As Long
    ws.Cells(SCHED_ROW_START, "A").Value = "Accrual Start"
    ws.Cells(SCHED_ROW_END, "A").Value = "Accrual End"
    ws.Cells(SCHED_ROW_PAYMENT, "A").Value = "Coupon Date / Payment Date"
    ws.Cells(SCHED_ROW_FIXING_DATE, "A").Value = "Fixing Date"
    ws.Cells(SCHED_ROW_DAYS, "A").Value = "Accrual Days"
    ws.Cells(SCHED_ROW_ACCRUAL, "A").Value = "Accrual Factor"
    ws.Cells(SCHED_ROW_FORWARD, "A").Value = "Forward Rate"
    ws.Cells(SCHED_ROW_COUPON_RATE, "A").Value = "Coupon Rate Used"
    ws.Cells(SCHED_ROW_PAY_DF, "A").Value = "Pay DF"
    ws.Cells(SCHED_ROW_FIXED_COUPON, "A").Value = "Fixed Coupon"
    ws.Cells(SCHED_ROW_FLOAT_COUPON, "A").Value = "Floating Coupon"
    ws.Cells(SCHED_ROW_FIXED_PV, "A").Value = "Fixed PV"
    ws.Cells(SCHED_ROW_FLOAT_PV, "A").Value = "Floating PV"
    ws.Cells(SCHED_ROW_NET_PV, "A").Value = "Net PV Float-Fixed"

    Dim useEom As Boolean
    useEom = USE_EOM_CONVENTION And IsBusinessMonthEnd(effectiveDate, holidays)

    Dim periodNo As Long
    Dim outCol As Long
    Dim rawStart As Date
    Dim rawEnd As Date
    Dim adjStart As Date
    Dim adjEnd As Date
    Dim payDate As Date
    Dim fixingDate As Date
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
        payDate = adjEnd
        fixingDate = PrecedingBusinessDay(adjStart, holidays)

        If rawStart <> adjStart Then nonBizRows.Add Array("Schedule Start", rawStart, adjStart, NonBusinessReason(rawStart, holidays))
        If rawEnd <> adjEnd Then nonBizRows.Add Array("Schedule End/Pay", rawEnd, adjEnd, NonBusinessReason(rawEnd, holidays))

        If payDate >= cashflowCutoffDate Then
            ws.Cells(SCHED_ROW_START, outCol).Value = adjStart
            ws.Cells(SCHED_ROW_END, outCol).Value = adjEnd
            ws.Cells(SCHED_ROW_PAYMENT, outCol).Value = payDate
            ws.Cells(SCHED_ROW_FIXING_DATE, outCol).Value = fixingDate

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

Private Sub ClearIrsOutputArea(ByVal ws As Worksheet)
    On Error GoTo Fail

    With ws.Range("A5:CC500")
        .UnMerge
        .Clear
    End With

    Exit Sub

Fail:
    Err.Raise Err.Number, , "Output area A5:CC500 could not be cleared. Check sheet protection or merged cells. " & Err.Description
End Sub

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
    payCell = ws.Cells(SCHED_ROW_PAYMENT, c).Address(False, False)
    fixingDateCell = ws.Cells(SCHED_ROW_FIXING_DATE, c).Address(False, False)
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
    On Error GoTo Fail

    Dim curveStep As String
    curveStep = "write curve headers"

    Dim headers As Variant
    Dim headerIndex As Long
    headers = Array("TENOR", "Date", "Par Rate", "Days From Base", "Interpolated Par Rate", "Accrual Days", "DF", "ZCR")
    For headerIndex = LBound(headers) To UBound(headers)
        ws.Cells(OUTPUT_HEADER_ROW, headerIndex + 1).Value = headers(headerIndex)
    Next headerIndex

    Dim rowByMonths As Object
    curveStep = "create row map"
    Set rowByMonths = CreateObject("Scripting.Dictionary")

    Dim useEom As Boolean
    curveStep = "determine EOM convention"
    useEom = USE_EOM_CONVENTION And IsBusinessMonthEnd(valuationDate, holidays)

    Dim n As Long
    Dim months As Long
    Dim r As Long
    Dim rawDate As Date
    Dim adjDate As Date

    r = OUTPUT_FIRST_ROW

    For n = 0 To curveQuarterCount
        months = n * 3
        curveStep = "write tenor row " & CStr(r) & " / " & TenorLabel(months)

        If months = 0 Then
            rawDate = valuationDate
            adjDate = valuationDate
        Else
            rawDate = IrsAddMonths(valuationDate, months, useEom)
            adjDate = AdjustModifiedFollowing(rawDate, holidays)
        End If

        ws.Cells(r, 1).Value = TenorLabel(months)
        ws.Cells(r, 2).Value = adjDate
        ws.Cells(r, 4).Value = CLng(adjDate - valuationDate)

        If keyRates.Exists(CStr(months)) Then
            ws.Cells(r, 3).Value = CDbl(keyRates(CStr(months)))
        End If

        rowByMonths(CStr(months)) = r

        If rawDate <> adjDate Then
            nonBizRows.Add Array(TenorLabel(months), rawDate, adjDate, NonBusinessReason(rawDate, holidays))
        End If

        r = r + 1
    Next n

    curveStep = "write curve formulas"
    WriteCurveFormulas ws, keyRates, keyMonths, rowByMonths, curveQuarterCount

    Exit Sub

Fail:
    Err.Raise Err.Number, , "WriteQuarterlyCurve failed while " & curveStep & ". " & Err.Description
End Sub

Private Sub WriteCurveFormulas(ByVal ws As Worksheet, ByVal keyRates As Object, _
                               ByVal keyMonths As Variant, ByVal rowByMonths As Object, _
                               ByVal curveQuarterCount As Long)
    On Error GoTo Fail

    Dim formulaStep As String
    formulaStep = "start value bootstrap"

    Dim n As Long
    Dim months As Long
    Dim r As Long
    Dim lowerMonths As Long
    Dim upperMonths As Long
    Dim lowerRow As Long
    Dim upperRow As Long
    Dim firstCouponRow As Long
    Dim dayBasis As Double
    Dim parRate As Double
    Dim lowerRate As Double
    Dim upperRate As Double
    Dim lowerDays As Double
    Dim upperDays As Double
    Dim currentDays As Double
    Dim accrualDays As Double
    Dim df As Double
    Dim zcr As Double
    Dim sumDfDays As Double
    Dim priorRow As Long

    firstCouponRow = OUTPUT_FIRST_ROW + 1
    dayBasis = CDbl(ws.Cells(INPUT_VALUE_ROW, COL_DAY_BASIS).Value)

    For n = 0 To curveQuarterCount
        months = n * 3
        formulaStep = "locate row for " & TenorLabel(months)
        r = CLng(rowByMonths(CStr(months)))
        currentDays = CDbl(ws.Cells(r, 4).Value)

        If months = 0 Then
            formulaStep = "write base curve row"
            parRate = CDbl(keyRates(CStr(months)))
            ws.Cells(r, 5).Value = parRate
            ws.Cells(r, 6).Value = 0
            ws.Cells(r, 7).Value = 1#
            ws.Cells(r, 8).Value = parRate
        Else
            If keyRates.Exists(CStr(months)) Then
                formulaStep = "use direct par rate for " & TenorLabel(months)
                parRate = CDbl(keyRates(CStr(months)))
            Else
                formulaStep = "find interpolation bounds for " & TenorLabel(months)
                FindInterpolationBounds months, keyMonths, lowerMonths, upperMonths
                lowerRow = CLng(rowByMonths(CStr(lowerMonths)))
                upperRow = CLng(rowByMonths(CStr(upperMonths)))
                lowerRate = CDbl(keyRates(CStr(lowerMonths)))
                upperRate = CDbl(keyRates(CStr(upperMonths)))
                lowerDays = CDbl(ws.Cells(lowerRow, 4).Value)
                upperDays = CDbl(ws.Cells(upperRow, 4).Value)

                formulaStep = "interpolate par rate for " & TenorLabel(months)
                If upperDays = lowerDays Then
                    Err.Raise vbObjectError + 103, , "Interpolation dates overlap for " & TenorLabel(months) & "."
                End If
                parRate = (upperRate - lowerRate) / (upperDays - lowerDays) * (currentDays - lowerDays) + lowerRate
            End If

            formulaStep = "bootstrap DF for " & TenorLabel(months)
            accrualDays = currentDays - CDbl(ws.Cells(r - 1, 4).Value)
            ws.Cells(r, 5).Value = parRate
            ws.Cells(r, 6).Value = accrualDays

            If months = 3 Then
                df = 1# / (1# + parRate / 100# * accrualDays / dayBasis)
            Else
                sumDfDays = 0#
                For priorRow = firstCouponRow To r - 1
                    sumDfDays = sumDfDays + CDbl(ws.Cells(priorRow, 7).Value) * CDbl(ws.Cells(priorRow, 6).Value)
                Next priorRow

                df = (dayBasis * 100# - parRate * sumDfDays) / (dayBasis * 100# + accrualDays * parRate)
            End If

            If df <= 0# Then
                Err.Raise vbObjectError + 104, , "Bootstrapped DF is not positive for " & TenorLabel(months) & "."
            End If

            formulaStep = "write DF/ZCR values for " & TenorLabel(months)
            zcr = -Log(df) * dayBasis / currentDays * 100#
            ws.Cells(r, 7).Value = df
            ws.Cells(r, 8).Value = zcr
        End If
    Next n

    Exit Sub

Fail:
    Err.Raise Err.Number, , "WriteCurveFormulas failed while " & formulaStep & ". " & Err.Description
End Sub

Private Sub WriteNpvSummary(ByVal ws As Worksheet, ByVal couponCount As Long)
    Dim firstCol As Long
    Dim lastCol As Long
    firstCol = SCHEDULE_FIRST_COL

    ws.Cells(SUMMARY_ROW, "A").Value = "PV Fixed"
    ws.Cells(SUMMARY_ROW, "C").Value = "PV Floating"
    ws.Cells(SUMMARY_ROW, "E").Value = "NPV Float-Fixed"
    ws.Cells(SUMMARY_ROW + 1, "A").Value = "View"
    ws.Cells(SUMMARY_ROW + 1, "B").Value = "Floating receiver / fixed payer"

    If couponCount <= 0 Then
        ws.Cells(SUMMARY_ROW, "B").Value = 0
        ws.Cells(SUMMARY_ROW, "D").Value = 0
        ws.Cells(SUMMARY_ROW, "F").Value = 0
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
        If IsDate(ws.Cells(SCHED_ROW_PAYMENT, c).Value) Then
            d = CDate(ws.Cells(SCHED_ROW_PAYMENT, c).Value)
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

Private Sub WriteDfLookupBox(ByVal ws As Worksheet)
    ws.Cells(SUMMARY_ROW, "J").Value = "DF Lookup Date"
    ws.Cells(SUMMARY_ROW, "K").NumberFormat = DATE_FORMAT
    ws.Cells(SUMMARY_ROW, "L").Value = "Daily DF (ZCR Linear)"
    ws.Cells(SUMMARY_ROW + 1, "L").Formula = "=IF(K" & (SUMMARY_ROW + 1) & "="""","""",IRS_DAILY_DF(K" & (SUMMARY_ROW + 1) & "))"
End Sub

Public Function IRS_DAILY_DF(ByVal targetDate As Variant, Optional ByVal sheetName As String = "") As Variant
    On Error GoTo Fail
    Application.Volatile True

    If Not IsDate(targetDate) Then
        IRS_DAILY_DF = CVErr(xlErrValue)
        Exit Function
    End If

    Dim ws As Worksheet
    If Len(sheetName) > 0 Then
        Set ws = ThisWorkbook.Worksheets(sheetName)
    ElseIf TypeName(Application.Caller) = "Range" Then
        Set ws = Application.Caller.Worksheet
    Else
        Set ws = ActiveSheet
    End If

    Dim d As Date
    d = CDate(targetDate)

    Dim baseDate As Date
    baseDate = CDate(ws.Cells(INPUT_VALUE_ROW, COL_VALUATION_DATE).Value)

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

    dayBasis = CDbl(ws.Cells(INPUT_VALUE_ROW, COL_DAY_BASIS).Value)

    For r = OUTPUT_FIRST_ROW To OUTPUT_FIRST_ROW + MAX_QUARTERS - 1
        If IsDate(ws.Cells(r, "B").Value) And IsDate(ws.Cells(r + 1, "B").Value) Then
            d0 = CDate(ws.Cells(r, "B").Value)
            d1 = CDate(ws.Cells(r + 1, "B").Value)

            If d >= d0 And d <= d1 Then
                zcr0 = CDbl(ws.Cells(r, "H").Value)
                zcr1 = CDbl(ws.Cells(r + 1, "H").Value)
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
        Set ws = ThisWorkbook.Worksheets(sheetName)
    ElseIf TypeName(Application.Caller) = "Range" Then
        Set ws = Application.Caller.Worksheet
    Else
        Set ws = ActiveSheet
    End If

    Dim d As Date
    d = CDate(targetDate)

    Dim baseDate As Date
    baseDate = CDate(ws.Cells(INPUT_VALUE_ROW, COL_VALUATION_DATE).Value)

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
        If IsDate(ws.Cells(r, "B").Value) And IsDate(ws.Cells(r + 1, "B").Value) Then
            d0 = CDate(ws.Cells(r, "B").Value)
            d1 = CDate(ws.Cells(r + 1, "B").Value)

            If d = d0 Then
                IRS_DAILY_DF_LOG_LINEAR = CDbl(ws.Cells(r, "G").Value)
                Exit Function
            End If

            If d > d0 And d <= d1 Then
                df0 = CDbl(ws.Cells(r, "G").Value)
                df1 = CDbl(ws.Cells(r + 1, "G").Value)
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
        ws.Range(ws.Cells(SCHED_ROW_START, SCHEDULE_FIRST_COL), ws.Cells(SCHED_ROW_FIXING_DATE, lastScheduleCol)).NumberFormat = DATE_FORMAT
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
    ws.Range(ws.Cells(SUMMARY_ROW + 1, "L"), ws.Cells(SUMMARY_ROW + 1, "L")).NumberFormat = RATE_FORMAT
    ws.Cells(SUMMARY_ROW + 1, "K").NumberFormat = DATE_FORMAT

    Dim lastCurveRow As Long
    lastCurveRow = OUTPUT_FIRST_ROW + curveQuarterCount

    With ws.Range(ws.Cells(OUTPUT_HEADER_ROW, "A"), ws.Cells(OUTPUT_HEADER_ROW, "H"))
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
    ws.Range(ws.Cells(OUTPUT_HEADER_ROW, "A"), ws.Cells(lastCurveRow, "H")).Borders.LineStyle = xlContinuous

    Dim r As Long
    For r = OUTPUT_FIRST_ROW To lastCurveRow
        If Len(ws.Cells(r, "C").Value) > 0 Then
            ws.Cells(r, "A").Interior.Color = vbYellow
        End If
    Next r

    SafeAutoFitColumns ws, "A:CC"
End Sub

Private Sub WriteNonBusinessLog(ByVal ws As Worksheet, ByVal nonBizRows As Collection, ByVal startRow As Long)
    If nonBizRows.Count = 0 Then Exit Sub

    ws.Cells(startRow, "A").Value = "Non-business day log"
    ws.Range(ws.Cells(startRow + 1, "A"), ws.Cells(startRow + 1, "D")).Value = Array("Item", "Original Date", "Adjusted Date", "Reason")

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

Private Sub EnsureCdFixingsSheet()
    Dim ws As Worksheet
    Set ws = GetOrCreateSheet(CD_FIXINGS_SHEET)

    If Len(ws.Cells(1, "A").Value) = 0 Then
        ws.Range("A1:C1").Value = Array("Date", "CD91 Rate", "Source")
        ws.Range("A:A").NumberFormat = DATE_FORMAT
        ws.Range("B:B").NumberFormat = RATE_FORMAT
        SafeAutoFitColumns ws, "A:C"
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
        If IsDate(ws.Cells(SCHED_ROW_FIXING_DATE, c).Value) And IsDate(ws.Cells(SCHED_ROW_PAYMENT, c).Value) Then
            fixingDate = CDate(ws.Cells(SCHED_ROW_FIXING_DATE, c).Value)
            payDate = CDate(ws.Cells(SCHED_ROW_PAYMENT, c).Value)

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
        If IsDate(ws.Cells(r, "A").Value) Then
            If CLng(CDate(ws.Cells(r, "A").Value)) = CLng(fixingDate) Then
                If IsNumeric(ws.Cells(r, "B").Value) Then
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
        If IsDate(ws.Cells(r, "A").Value) Then
            If CLng(CDate(ws.Cells(r, "A").Value)) = CLng(fixingDate) Then
                ws.Cells(r, "B").Value = rate
                ws.Cells(r, "C").Value = source
                Exit Sub
            End If
        End If
    Next r

    r = lastRow + 1
    ws.Cells(r, "A").Value = fixingDate
    ws.Cells(r, "B").Value = rate
    ws.Cells(r, "C").Value = source

    ws.Range("A:A").NumberFormat = DATE_FORMAT
    ws.Range("B:B").NumberFormat = RATE_FORMAT
    SafeAutoFitColumns ws, "A:C"
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
        shp.Name = REFRESH_BUTTON_NAME
    End If

    With shp
        .Left = ws.Range("Y2").Left
        .Top = ws.Range("Y2").Top
        .Width = ws.Range("Y2:Z3").Width
        .Height = ws.Range("Y2:Z3").Height
        .OnAction = "'" & ThisWorkbook.Name & "'!RefreshIRSNpvTool"
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
        shp.Name = CALENDAR_UPDATE_BUTTON_NAME
    End If

    With shp
        .Left = ws.Range("Y5").Left
        .Top = ws.Range("Y5").Top
        .Width = ws.Range("Y5:Z6").Width
        .Height = ws.Range("Y5:Z6").Height
        .OnAction = "'" & ThisWorkbook.Name & "'!UpdateIrsCalendarCache2020To2040"
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
    Set ws = ActiveSheet

    Application.ScreenUpdating = False
    Application.EnableEvents = False

    Dim covered As Object
    Set covered = CreateObject("Scripting.Dictionary")

    Dim holidays As Object
    Set holidays = CreateObject("Scripting.Dictionary")

    Dim y As Long
    Dim ok As Boolean

    For y = CALENDAR_UPDATE_FIRST_YEAR To CALENDAR_UPDATE_LAST_YEAR
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

    WriteCalendarSheet holidays
    SetupIRSNpvSheet ws

    MsgBox "IRS_Calendar updated for " & CStr(CALENDAR_UPDATE_FIRST_YEAR) & "-" & CStr(CALENDAR_UPDATE_LAST_YEAR) & ".", vbInformation

CleanExit:
    Application.EnableEvents = True
    Application.ScreenUpdating = True
    Exit Sub

Fail:
    Application.EnableEvents = True
    Application.ScreenUpdating = True
    MsgBox "Calendar update failed: " & Err.Description, vbCritical
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
    SafeAutoFitColumns ws, "A:D"
End Sub

Private Sub SafeAutoFitColumns(ByVal ws As Worksheet, ByVal columnAddress As String)
    On Error Resume Next
    ws.Columns(columnAddress).AutoFit
    On Error GoTo 0
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
        If ThisWorkbook.ProtectStructure Then
            Err.Raise vbObjectError + 401, , "Workbook structure is protected. Unprotect workbook structure so the required sheet can be created: " & sheetName
        End If

        Set GetOrCreateSheet = ThisWorkbook.Worksheets.Add(After:=ThisWorkbook.Worksheets(ThisWorkbook.Worksheets.Count))
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

Private Function KoreanYearEndLabel() As String
    KoreanYearEndLabel = ChrW$(&HC5F0) & ChrW$(&HB9D0)
End Function

Private Function KoreanMarketCloseLabel() As String
    KoreanMarketCloseLabel = ChrW$(&HD3D0) & ChrW$(&HC7A5)
End Function
