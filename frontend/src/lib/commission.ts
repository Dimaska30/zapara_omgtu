import type { SearchItem } from './schedule';

// Эти ID — значения person из API расписания ОмГТУ. Они подходят для /schedule/person/{id}.
const person = (id: string, label: string): SearchItem => ({ id, label, description: '' });

const staff = {
  belim: person('999', 'Белим С. Ю.'),
  boldovskaya: person('1003031', 'Болдовская Т. Е.'),
  bugaenko: person('1001154', 'Бугаенко И. Е.'),
  veremchuk: person('1001133', 'Веремчук Н. С.'),
  grigor: person('281474976861033', 'Григор А. А.'),
  gulyanov: person('1001117', 'Гулянов Р. Г.'),
  gunenkov: person('1003026', 'Гуненков М. Ю.'),
  devyaterikova: person('1004080', 'Девятерикова М. В.'),
  zharkikh: person('1001121', 'Жарких А. А.'),
  zaozerskaya: person('1003027', 'Заозерская Л. А.'),
  zubova: person('1001130', 'Зубова Ю. И.'),
  zykin: person('574', 'Зыкин С. В.'),
  zykina: person('573', 'Зыкина А. В.'),
  kazakov: person('794360', 'Казаков С. Г.'),
  kobernik: person('665', 'Коберник Е. Г.'),
  krumina: person('729', 'Крумина К. В.'),
  malitsky: person('1001178', 'Малицкий А. С.'),
  miroshnichenko: person('281474976861590', 'Мирошниченко А. О.'),
  moiseeva: person('1003032', 'Моисеева Н. А.'),
  morar: person('782570', 'Морарь Е. В.'),
  munko_v: person('36240', 'Мунько В. В.'),
  munko_s: person('1001078', 'Мунько С. Н.'),
  pleskunov: person('1001142', 'Плескунов Д. А.'),
  polyakova: person('1001132', 'Полякова Т. А.'),
  prokhorov: person('1076', 'Прохоров П. В.'),
  revina: person('1092', 'Ревина И. В.'),
  savin: person('1001156', 'Савин А. Ю.'),
  samatov: person('1001051', 'Саматов А. П.'),
  tyumentsev: person('1004091', 'Тюменцев Е. А.'),
  fedorov: person('1328', 'Федоров И. В.'),
  chibikova: person('1386', 'Чибикова Т. В.'),
  shevchik: person('1001190', 'Шевчик Н. М.'),
  shepelev: person('1001129', 'Шепелев Н. С.')
};

export type CommissionGroup = { id: string; label: string; people: SearchItem[] };

export const COMMISSION_GROUPS: CommissionGroup[] = [
  { id: 'math', label: 'Математика', people: [staff.belim, staff.boldovskaya, staff.veremchuk, staff.devyaterikova, staff.zaozerskaya, staff.zykin, staff.zykina, staff.kazakov, staff.munko_v, staff.polyakova, staff.revina] },
  { id: 'programming', label: 'Программирование', people: [staff.bugaenko, staff.grigor, staff.gulyanov, staff.gunenkov, staff.zharkikh, staff.zubova, staff.malitsky, staff.miroshnichenko, staff.munko_s, staff.pleskunov, staff.prokhorov, staff.savin, staff.samatov, staff.tyumentsev, staff.shepelev] },
  { id: 'informatics', label: 'Информатика', people: [staff.zubova, staff.kobernik, staff.krumina, staff.moiseeva, staff.pleskunov, staff.fedorov, staff.chibikova] },
  { id: 'engineering', label: 'Инженерия', people: [staff.zharkikh, staff.moiseeva, staff.morar, staff.pleskunov, staff.shevchik] },
  { id: 'management', label: 'Менеджмент', people: [staff.zubova, staff.krumina, staff.moiseeva, staff.pleskunov, staff.chibikova] },
  { id: 'ai', label: 'Машинное обучение и ИИ', people: [staff.bugaenko, staff.gunenkov, staff.gulyanov, staff.grigor, staff.zubova, staff.malitsky, staff.moiseeva, staff.munko_v, staff.pleskunov] }
];
