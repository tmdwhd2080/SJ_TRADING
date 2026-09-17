# -*- coding: utf-8 -*-
"""
BOT 통합 실행 파일 (run.py)
════════════════════════════════════════════════════════════════
이 파일을 실행하면 6개의 모든 BOT이 순서대로 실행됩니다.

    python BOT/run.py                      # 전체 실행
    python BOT/run.py --bot 고용동향      # 특정 BOT만 실행
    python BOT/run.py --config             # 설정 확인 후 종료

════════════════════════════════════════════════════════════════
실행 순서:
  [1] 고용동향         (api_고용동향.py)
  [2] 글로벌매크로     (api_글로벌매크로.py)
  [3] 리뷰            (api_리뷰.py)
  [4] 산업활동동향     (api_산업활동동향.py)
  [5] 수출입동향       (api_수출입.py)
  [6] 통화정책         (api_통화정책.py)

모든 설정은 config.py에서 한번에 관리됩니다.
════════════════════════════════════════════════════════════════
"""

import sys
import time
import traceback
import argparse
import warnings
warnings.filterwarnings('ignore')


# 오류 발생 시 전체 중단 여부(false 시 오류 무시하고 그대로 진행)
STOP_ON_ERROR = False



def _header(title: str, width: int = 64):
    """헤더 출력"""
    print("\n" + "═" * width)
    pad = (width - len(title) - 2) // 2
    print(f"  {'─'*pad}  {title}  {'─'*pad}")
    print("═" * width)


def _ok(msg: str):
    """성공 메시지"""
    print(f"  ✅  {msg}")


def _warn(msg: str):
    """경고 메시지"""
    print(f"  ⚠️   {msg}")


def _err(msg: str):
    """오류 메시지"""
    print(f"  ❌  {msg}")


def _run_bot(bot_name: str, module_name: str):

    _header(bot_name)
    t0 = time.time()
    
    try:
        # 동적 import
        module = __import__(module_name, fromlist=['main'])
        main_func = getattr(module, 'main', None)
        
        if main_func is None:
            _err(f"'{module_name}'에서 main() 함수를 찾을 수 없습니다.")
            return None, False
        
        # 실행
        result = main_func()
        elapsed = time.time() - t0
        _ok(f"{bot_name} 완료  ({elapsed:.1f}초)")
        return result, True
        
    except Exception as e:
        elapsed = time.time() - t0
        _err(f"{bot_name} 실패  ({elapsed:.1f}초)")
        _err(f"오류: {str(e)[:100]}")
        
        if STOP_ON_ERROR:
            traceback.print_exc()
            raise
        else:
            _warn("STOP_ON_ERROR=False → 다음 BOT 계속 진행")
            traceback.print_exc()
        
        return None, False


def load_and_display_config():
    """설정 정보 로드 및 출력"""
    try:
        from 보고서_API.BOT.config import all_bots, TRAINING_PDF_DIR, INPUT_DIR, OUTPUT_DIR
        
        _header("BOT 설정 정보")
        
        print(f"\n[기본 경로]")
        print(f"  Training Dir: {TRAINING_PDF_DIR}")
        print(f"  Input Dir:    {INPUT_DIR}")
        print(f"  Output Dir:   {OUTPUT_DIR}")
        
        print(f"\n[BOT 목록 및 설정]")
        for i, config in enumerate(all_bots, 1):
            print(f"\n  {i}. {config['name']}")
            for key, value in config.items():
                if key != 'name' and not key.endswith('dir') and not key.endswith('file'):
                    if len(str(value)) > 50:
                        print(f"     {key}: {str(value)[:50]}...")
                    else:
                        print(f"     {key}: {value}")
        
        _ok("설정 로드 완료")
        return True
        
    except ImportError:
        _err("config.py를 찾을 수 없습니다. config.py를 먼저 생성하세요.")
        return False


def run_all_bots():
    """모든 BOT 실행"""
    
    _header("BOT 통합 실행 시작")
    
    # BOT 목록: (한글명, 모듈명)
    bots = [
        ("고용동향",       "api_고용동향"),
        ("글로벌매크로",   "api_글로벌매크로"),
        ("리뷰",          "api_리뷰"),
        ("산업활동동향",   "api_산업활동동향"),
        ("수출입동향",     "api_수출입"),
        ("통화정책",       "api_통화정책"),
    ]
    
    results = {}
    reports = {}
    total_time = time.time()
    
    # 각 BOT 실행
    for bot_name, module_name in bots:
        report, success = _run_bot(bot_name, module_name)
        results[bot_name] = success
        if success and report:
            reports[bot_name] = report
    
    elapsed_total = time.time() - total_time
    
    _header("전체 실행 결과 요약")
    
    success_count = sum(1 for v in results.values() if v)
    total_count = len(results)
    
    print(f"\n[결과]")
    for bot_name, success in results.items():
        status = "✅ 성공" if success else "❌ 실패"
        print(f"  {status}  {bot_name}")
    
    print(f"\n[통계]")
    print(f"  총 BOT: {total_count}개")
    print(f"  성공: {success_count}개")
    print(f"  실패: {total_count - success_count}개")
    print(f"  총 소요 시간: {elapsed_total:.1f}초")
    
    # 최종 요약 파일 생성
    if reports:
        summary_content = _generate_summary_file(reports, bots)
        _save_summary_file(summary_content)
    
    print("\n" + "═" * 64)
    
    return success_count == total_count


def _generate_summary_file(reports: dict, bots: list) -> str:
    """모든 보고서의 최종 요약 생성"""
    summary_lines = ["각 BOT의 최종 산출 보고서 요약"]
    summary_lines.append("=" * 64)
    summary_lines.append("")
    
    for bot_name, module_name in bots:
        if bot_name in reports:
            summary_lines.append(f"[{bot_name}]")
            summary_lines.append("-" * 64)
            summary_lines.append(reports[bot_name])
            summary_lines.append("")
    
    return "\n".join(summary_lines)


def _save_summary_file(content: str):
    """최종 요약 파일 저장"""
    try:
        from 보고서_API.BOT.config import OUTPUT_DIR
        output_path = OUTPUT_DIR
    except:
        output_path = "pdf_output"
    
    try:
        import os
        os.makedirs(output_path, exist_ok=True)
        
        summary_file = os.path.join(output_path, "00_최종_요약보고서.txt")
        with open(summary_file, "w", encoding="utf-8") as f:
            f.write(content)
        
        _ok(f"최종 요약 저장: {summary_file}")
        
    except Exception as e:
        _err(f"요약 파일 저장 실패: {e}")


def run_specific_bot(bot_name: str):
    """특정 BOT만 실행"""
    
    # 한글명 -> 모듈명 맵
    bot_map = {
        "고용동향": "api_고용동향",
        "글로벌매크로": "api_글로벌매크로",
        "리뷰": "api_리뷰",
        "산업활동동향": "api_산업활동동향",
        "수출입동향": "api_수출입",
        "통화정책": "api_통화정책",
    }
    
    if bot_name not in bot_map:
        _err(f"'{bot_name}'은 존재하지 않습니다.")
        print(f"  사용 가능한 BOT: {', '.join(bot_map.keys())}")
        return False
    
    module_name = bot_map[bot_name]
    _, success = _run_bot(bot_name, module_name)
    return success


def main():
    """메인"""
    
    parser = argparse.ArgumentParser(
        description="BOT 통합 실행 프로그램",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  python BOT/run.py                    # 전체 BOT 실행
  python BOT/run.py --bot 고용동향    # 고용동향 BOT만 실행
  python BOT/run.py --config           # 설정 확인 후 종료
        """
    )
    
    parser.add_argument(
        '--bot',
        type=str,
        help='실행할 특정 BOT명 (예: 고용동향)'
    )
    
    parser.add_argument(
        '--config',
        action='store_true',
        help='설정 정보만 출력하고 종료'
    )
    
    args = parser.parse_args()
    
    # 설정 확인 옵션
    if args.config:
        return 0 if load_and_display_config() else 1
    
    # 특정 BOT 실행
    if args.bot:
        success = run_specific_bot(args.bot)
        return 0 if success else 1
    
    # 모든 BOT 실행
    success = run_all_bots()
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
# python BOT/run.py